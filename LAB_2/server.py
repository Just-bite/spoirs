import socket
import os
import datetime
import select
import struct

HOST = '0.0.0.0'
PORT = 9090
CHUNK_SIZE = 1400
WINDOW_SIZE = 32

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

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
            except Exception:
                pass
        else:
            retries += 1
            for seq in range(base, next_seq):
                if seq in window:
                    sock.sendto(window[seq], dest_addr)

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
            elif seq < expected_seq:
                sock.sendto(struct.pack('<I', seq), dest_addr)
            else:
                if expected_seq > 0:
                    sock.sendto(struct.pack('<I', expected_seq - 1), dest_addr)
        except socket.timeout:
            break
            
    sock.settimeout(None)

def handle_download(sock, addr, parts):
    if len(parts) < 2:
        return
    filename = parts[1]
    offset = int(parts[2]) if len(parts) > 2 else 0
    
    if not os.path.exists(filename) or not os.path.isfile(filename):
        sock.sendto(b"ERROR file not found", addr)
        return
        
    filesize = os.path.getsize(filename)
    sock.sendto(f"OK {filesize}".encode(), addr)
    
    if offset >= filesize:
        return
        
    with open(filename, 'rb') as f:
        f.seek(offset)
        reliable_send(sock, addr, f, filesize - offset)

def handle_upload(sock, addr, parts):
    if len(parts) < 3:
        return
    filename = parts[1]
    filesize = int(parts[2])
    
    offset = os.path.getsize(filename) if os.path.exists(filename) else 0
    sock.sendto(f"OK {offset}".encode(), addr)
    
    if offset >= filesize:
        return
        
    with open(filename, 'ab') as f:
        reliable_recv(sock, addr, f, filesize - offset)

def process_command(sock, addr, data):
    msg = data.decode('utf-8', errors='ignore').strip()
    parts = msg.split()
    if not parts:
        return
        
    cmd = parts[0].upper()
    if cmd == 'ECHO':
        sock.sendto(" ".join(parts[1:]).encode(), addr)
    elif cmd == 'TIME':
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sock.sendto(now.encode(), addr)
    elif cmd == 'DOWNLOAD':
        handle_download(sock, addr, parts)
    elif cmd == 'UPLOAD':
        handle_upload(sock, addr, parts)
    elif cmd in ('EXIT', 'QUIT', 'CLOSE'):
        pass
    else:
        sock.sendto(b"UNKNOWN COMMAND", addr)

def start_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    
    print(f"UDP Server is listening on {HOST}:{PORT}")
    print(f"Local IP for client: {get_local_ip()}")
    
    while True:
        try:
            r, _, _ = select.select([s], [], [], 1.0)
            if not r:
                continue
            data, addr = s.recvfrom(4096)
            process_command(s, addr, data)
        except KeyboardInterrupt:
            break
        except Exception:
            pass
            
    s.close()

if __name__ == '__main__':
    start_server()