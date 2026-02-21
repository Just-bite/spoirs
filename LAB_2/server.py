import socket
import os
import datetime
import select
import struct
import time

HOST = '0.0.0.0'
PORT = 9090
CHUNK_SIZE = 32768
WINDOW_SIZE = 64
TIMEOUT = 0.5

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def send_file_udp(sock, addr, filename, offset):
    try:
        filesize = os.path.getsize(filename)
        sock.sendto(f"OK {filesize}".encode(), addr)
        
        f = open(filename, 'rb')
        f.seek(offset)
        
        base = 0
        next_seq = 0
        total_chunks = (filesize - offset + CHUNK_SIZE - 1) // CHUNK_SIZE
        window_buffer = {}

        while base < total_chunks:
            while next_seq < base + WINDOW_SIZE and next_seq < total_chunks:
                if next_seq not in window_buffer:
                    f.seek(offset + next_seq * CHUNK_SIZE)
                    data = f.read(CHUNK_SIZE)
                    packet = struct.pack('I', next_seq) + data
                    window_buffer[next_seq] = packet
                
                sock.sendto(window_buffer[next_seq], addr)
                next_seq += 1

            ready, _, _ = select.select([sock], [], [], TIMEOUT)
            if ready:
                try:
                    data, _ = sock.recvfrom(1024)
                    ack_seq = struct.unpack('I', data)[0]
                    if ack_seq >= base:
                        for i in range(base, ack_seq + 1):
                            if i in window_buffer:
                                del window_buffer[i]
                        base = ack_seq + 1
                except:
                    pass
            else:
                next_seq = base

        f.close()
    except Exception:
        sock.sendto(b"ERROR during transfer", addr)

def recv_file_udp(sock, addr, filename, filesize):
    try:
        sock.sendto(b"OK", addr)
        f = open(filename, 'wb')
        expected_seq = 0
        total_chunks = (filesize + CHUNK_SIZE - 1) // CHUNK_SIZE
        
        sock.settimeout(5.0)
        
        while expected_seq < total_chunks:
            try:
                packet, src = sock.recvfrom(CHUNK_SIZE + 16)
                if src != addr:
                    continue
                
                seq = struct.unpack('I', packet[:4])[0]
                data = packet[4:]
                
                if seq == expected_seq:
                    f.write(data)
                    ack_packet = struct.pack('I', seq)
                    sock.sendto(ack_packet, addr)
                    expected_seq += 1
                elif seq < expected_seq:
                    ack_packet = struct.pack('I', seq)
                    sock.sendto(ack_packet, addr)
                else:
                    ack_packet = struct.pack('I', expected_seq - 1)
                    sock.sendto(ack_packet, addr)
                    
            except socket.timeout:
                break
                
        f.close()
        sock.settimeout(None)
    except Exception:
        pass

def start_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((HOST, PORT))
    
    print(f"UDP Server listening on {HOST}:{PORT}")
    print(f"Local IP: {get_local_ip()}")
    
    while True:
        try:
            r, _, _ = select.select([s], [], [], 1.0)
            if not r:
                continue
                
            data, addr = s.recvfrom(4096)
            msg = data.decode('utf-8', errors='ignore').strip()
            parts = msg.split()
            
            if not parts:
                continue
                
            cmd = parts[0].upper()
            
            if cmd == 'ECHO':
                response = " ".join(parts[1:])
                s.sendto(response.encode(), addr)
                
            elif cmd == 'TIME':
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                s.sendto(now.encode(), addr)
                
            elif cmd == 'DOWNLOAD':
                if len(parts) < 2:
                    s.sendto(b"ERROR usage: DOWNLOAD <filename>", addr)
                    continue
                filename = parts[1]
                offset = int(parts[2]) if len(parts) > 2 else 0
                
                if os.path.exists(filename):
                    send_file_udp(s, addr, filename, offset)
                else:
                    s.sendto(b"ERROR file not found", addr)
                    
            elif cmd == 'UPLOAD':
                if len(parts) < 3:
                    s.sendto(b"ERROR usage: UPLOAD <filename> <size>", addr)
                    continue
                filename = parts[1]
                filesize = int(parts[2])
                recv_file_udp(s, addr, filename, filesize)
                
            elif cmd in ('EXIT', 'QUIT', 'CLOSE'):
                s.sendto(b"GOODBYE", addr)
                
            else:
                s.sendto(b"UNKNOWN COMMAND", addr)
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            
    s.close()

if __name__ == '__main__':
    start_server()