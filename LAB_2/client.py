import socket
import os
import sys
import time
import struct
import select

HOST = '127.0.0.1'
PORT = 9090
CHUNK_SIZE = 1400
WINDOW_SIZE = 32

def calc_bitrate(bytes_transferred, duration):
    if duration <= 0:
        duration = 0.001
    mbps = ((bytes_transferred * 8) / duration) / 1024 / 1024
    print(f"Transfer finished. Bitrate: {mbps:.2f} Mbps")

def reliable_send(sock, dest_addr, f, remaining_size):
    base = 0
    next_seq = 0
    window = {}
    total_chunks = (remaining_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    retries = 0
    
    while base < total_chunks and retries < 50:
        while next_seq < base + WINDOW_SIZE and next_seq < total_chunks:
            chunk = f.read(CHUNK_SIZE)
            window[next_seq] = struct.pack('<I', next_seq) + chunk
            sock.sendto(window[next_seq], dest_addr)
            next_seq += 1
            
        r, _, _ = select.select([sock], [], [], 0.1)
        if r:
            try:
                ack_data, _ = sock.recvfrom(1024)
                ack_seq = struct.unpack('<I', ack_data[:4])[0]
                if ack_seq >= base:
                    for i in range(base, ack_seq + 1):
                        window.pop(i, None)
                    base = ack_seq + 1
                    retries = 0
                    sys.stdout.write(f"\rProgress: {base}/{total_chunks} chunks")
                    sys.stdout.flush()
            except Exception:
                pass
        else:
            retries += 1
            for seq in range(base, next_seq):
                if seq in window:
                    sock.sendto(window[seq], dest_addr)
    print()

def reliable_recv(sock, dest_addr, f, remaining_size):
    expected_seq = 0
    total_chunks = (remaining_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    sock.settimeout(3.0)
    
    while expected_seq < total_chunks:
        try:
            packet, addr = sock.recvfrom(CHUNK_SIZE + 16)
            if addr != dest_addr:
                continue
                
            seq = struct.unpack('<I', packet[:4])[0]
            if seq == expected_seq:
                f.write(packet[4:])
                sock.sendto(struct.pack('<I', seq), dest_addr)
                expected_seq += 1
                if expected_seq % 50 == 0 or expected_seq == total_chunks:
                    sys.stdout.write(f"\rProgress: {expected_seq}/{total_chunks} chunks")
                    sys.stdout.flush()
            elif seq < expected_seq:
                sock.sendto(struct.pack('<I', seq), dest_addr)
            else:
                if expected_seq > 0:
                    sock.sendto(struct.pack('<I', expected_seq - 1), dest_addr)
        except socket.timeout:
            break
            
    sock.settimeout(None)
    print()

def do_download(sock, addr, parts):
    if len(parts) < 2:
        print("Usage: DOWNLOAD <filename>")
        return
        
    filename = parts[1]
    offset = os.path.getsize(filename) if os.path.exists(filename) else 0
    
    sock.sendto(f"DOWNLOAD {filename} {offset}".encode(), addr)
    sock.settimeout(2.0)
    try:
        resp, _ = sock.recvfrom(1024)
    except socket.timeout:
        print("Server not responding")
        return
    finally:
        sock.settimeout(None)
        
    resp_parts = resp.decode().split()
    if not resp_parts or resp_parts[0] != "OK":
        print(resp.decode())
        return
        
    filesize = int(resp_parts[1])
    if offset >= filesize:
        print("File completely downloaded.")
        return
        
    print(f"Downloading from offset {offset}...")
    start_time = time.time()
    with open(filename, 'ab') as f:
        reliable_recv(sock, addr, f, filesize - offset)
    calc_bitrate(filesize - offset, time.time() - start_time)

def do_upload(sock, addr, parts):
    if len(parts) < 2:
        print("Usage: UPLOAD <filename>")
        return
        
    filename = parts[1]
    if not os.path.exists(filename):
        print("File not found locally.")
        return
        
    filesize = os.path.getsize(filename)
    sock.sendto(f"UPLOAD {filename} {filesize}".encode(), addr)
    
    sock.settimeout(2.0)
    try:
        resp, _ = sock.recvfrom(1024)
    except socket.timeout:
        print("Server not responding")
        return
    finally:
        sock.settimeout(None)
        
    resp_parts = resp.decode().split()
    if not resp_parts or resp_parts[0] != "OK":
        print("Upload refused")
        return
        
    offset = int(resp_parts[1])
    if offset >= filesize:
        print("File completely uploaded.")
        return
        
    print(f"Uploading from offset {offset}...")
    start_time = time.time()
    with open(filename, 'rb') as f:
        f.seek(offset)
        reliable_send(sock, addr, f, filesize - offset)
    calc_bitrate(filesize - offset, time.time() - start_time)

def start_client():
    global HOST, PORT
    
    user_host = input(f"Enter server IP (default {HOST}): ").strip()
    if user_host:
        HOST = user_host
    user_port = input(f"Enter server port (default {PORT}): ").strip()
    if user_port:
        PORT = int(user_port)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_addr = (HOST, PORT)
    
    while True:
        try:
            cmd = input("> ").strip()
            if not cmd:
                continue
                
            parts = cmd.split()
            command = parts[0].upper()
            
            if command in ('EXIT', 'QUIT', 'CLOSE'):
                s.sendto(cmd.encode(), server_addr)
                break
            elif command == 'DOWNLOAD':
                do_download(s, server_addr, parts)
            elif command == 'UPLOAD':
                do_upload(s, server_addr, parts)
            else:
                s.sendto(cmd.encode(), server_addr)
                s.settimeout(2.0)
                try:
                    data, _ = s.recvfrom(4096)
                    print(data.decode())
                except socket.timeout:
                    print("Timeout")
                s.settimeout(None)
                
        except KeyboardInterrupt:
            break
        except Exception:
            pass
            
    s.close()

if __name__ == '__main__':
    start_client()