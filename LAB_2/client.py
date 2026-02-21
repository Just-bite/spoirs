import socket
import os
import sys
import time
import struct
import select

HOST = '127.0.0.1'
PORT = 9090
CHUNK_SIZE = 32768
WINDOW_SIZE = 64
TIMEOUT = 0.5

def calc_bitrate(bytes_transferred, duration):
    if duration <= 0:
        duration = 0.001
    mbps = ((bytes_transferred * 8) / duration) / 1024 / 1024
    print(f"Transfer finished. Bitrate: {mbps:.2f} Mbps")

def udp_download(sock, filename, offset):
    try:
        sock.settimeout(2.0)
        data, _ = sock.recvfrom(1024)
        resp = data.decode().split()
        
        if resp[0] != 'OK':
            print(f"Server error: {data.decode()}")
            return

        filesize = int(resp[1])
        print(f"Downloading {filename} ({filesize} bytes)...")
        
        f = open(filename, 'ab')
        expected_seq = 0
        total_chunks = (filesize - offset + CHUNK_SIZE - 1) // CHUNK_SIZE
        bytes_recvd = 0
        start_time = time.time()
        
        sock.settimeout(5.0)
        
        while expected_seq < total_chunks:
            try:
                packet, addr = sock.recvfrom(CHUNK_SIZE + 16)
                seq = struct.unpack('I', packet[:4])[0]
                chunk = packet[4:]
                
                if seq == expected_seq:
                    f.write(chunk)
                    bytes_recvd += len(chunk)
                    ack = struct.pack('I', seq)
                    sock.sendto(ack, addr)
                    expected_seq += 1
                    
                    if expected_seq % 100 == 0:
                        sys.stdout.write(f"\rChunks: {expected_seq}/{total_chunks}")
                        sys.stdout.flush()
                elif seq < expected_seq:
                    ack = struct.pack('I', seq)
                    sock.sendto(ack, addr)
                else:
                    ack = struct.pack('I', expected_seq - 1)
                    sock.sendto(ack, addr)
                    
            except socket.timeout:
                print("\nTransfer timeout.")
                break
                
        f.close()
        sock.settimeout(None)
        print()
        calc_bitrate(bytes_recvd, time.time() - start_time)
        
    except Exception as e:
        print(f"Download error: {e}")

def udp_upload(sock, filename):
    try:
        filesize = os.path.getsize(filename)
        sock.sendto(f"UPLOAD {os.path.basename(filename)} {filesize}".encode(), (HOST, PORT))
        
        sock.settimeout(2.0)
        data, addr = sock.recvfrom(1024)
        if data.decode() != 'OK':
            print(f"Server refused upload: {data.decode()}")
            return
            
        print(f"Uploading {filename} ({filesize} bytes)...")
        
        f = open(filename, 'rb')
        base = 0
        next_seq = 0
        total_chunks = (filesize + CHUNK_SIZE - 1) // CHUNK_SIZE
        window_buffer = {}
        start_time = time.time()
        
        while base < total_chunks:
            while next_seq < base + WINDOW_SIZE and next_seq < total_chunks:
                if next_seq not in window_buffer:
                    f.seek(next_seq * CHUNK_SIZE)
                    chunk = f.read(CHUNK_SIZE)
                    packet = struct.pack('I', next_seq) + chunk
                    window_buffer[next_seq] = packet
                
                sock.sendto(window_buffer[next_seq], addr)
                next_seq += 1
                
            ready, _, _ = select.select([sock], [], [], TIMEOUT)
            if ready:
                try:
                    ack_data, _ = sock.recvfrom(1024)
                    ack_seq = struct.unpack('I', ack_data)[0]
                    if ack_seq >= base:
                        for i in range(base, ack_seq + 1):
                            if i in window_buffer:
                                del window_buffer[i]
                        base = ack_seq + 1
                        sys.stdout.write(f"\rChunks: {base}/{total_chunks}")
                        sys.stdout.flush()
                except:
                    pass
            else:
                next_seq = base
                
        f.close()
        print()
        calc_bitrate(filesize, time.time() - start_time)
        
    except Exception as e:
        print(f"Upload error: {e}")

def start_client():
    global HOST, PORT
    
    user_host = input(f"Enter server IP (default {HOST}): ").strip()
    if user_host:
        HOST = user_host
    user_port = input(f"Enter server port (default {PORT}): ").strip()
    if user_port:
        PORT = int(user_port)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print(f"UDP Client ready. Connecting to {HOST}:{PORT}")
    
    while True:
        try:
            cmd = input("> ").strip()
            if not cmd:
                continue
                
            parts = cmd.split()
            command = parts[0].upper()
            
            if command in ('EXIT', 'QUIT', 'CLOSE'):
                break
                
            if command == 'DOWNLOAD':
                if len(parts) < 2:
                    print("Usage: DOWNLOAD <filename>")
                    continue
                filename = parts[1]
                offset = os.path.getsize(filename) if os.path.exists(filename) else 0
                s.sendto(f"DOWNLOAD {filename} {offset}".encode(), (HOST, PORT))
                udp_download(s, filename, offset)
                
            elif command == 'UPLOAD':
                if len(parts) < 2:
                    print("Usage: UPLOAD <filename>")
                    continue
                udp_upload(s, parts[1])
                
            else:
                s.sendto(cmd.encode(), (HOST, PORT))
                s.settimeout(2.0)
                try:
                    data, _ = s.recvfrom(4096)
                    print(data.decode())
                except socket.timeout:
                    print("Request timed out.")
                s.settimeout(None)
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            
    s.close()

if __name__ == '__main__':
    start_client()