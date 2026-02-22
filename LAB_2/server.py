import socket
import os
import sys
import struct
import select
from rudp import RUDPConnection, TYPE_SYN, TYPE_ACK

HOST = '0.0.0.0'
PORT = 9090

def handle_request(rudp, data):
    try:
        msg = data.decode('utf-8', errors='ignore').strip()
    except: return True
    
    if not msg: return True
    parts = msg.split()
    cmd = parts[0].upper()
    print(f"Command: {cmd}")
    
    if cmd == 'ECHO':
        rudp.send_reliable_data((" ".join(parts[1:]) + "\n").encode())
        
    elif cmd == 'TIME':
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n"
        rudp.send_reliable_data(now.encode())
        
    elif cmd == 'DOWNLOAD':
        if len(parts) < 2: return True
        filename = parts[1]
        if not os.path.exists(filename):
            rudp.send_reliable_data(b"ERROR file not found\n")
            return True
            
        size = os.path.getsize(filename)
        # 1. Отправляем размер
        rudp.send_reliable_data(f"OK {size}\n".encode())
        
        # 2. Ждем готовности (синхронизация)
        print("Waiting for client READY...")
        confirm = rudp.recv_reliable_data(timeout=10.0) # Ждем READY 10 сек
        
        if confirm and b'READY' in confirm:
            print(f"Sending {filename} ({size} bytes)...")
            rudp.send_file_bulk(filename)
            print("Transfer finished.")
        else:
            print("Client handshake timeout.")

    elif cmd == 'UPLOAD':
        rudp.send_reliable_data(b"ERROR Not implemented\n")
        
    elif cmd in ('EXIT', 'QUIT'):
        return False
    else:
        rudp.send_reliable_data(b"UNKNOWN COMMAND\n")
        
    return True

def start_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    sock.setblocking(0)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
    except: pass
    
    print(f"UDP Server on {PORT}")
    
    while True:
        try:
            readable, _, _ = select.select([sock], [], [], 0.5)
            if readable:
                try:
                    data, addr = sock.recvfrom(1024)
                    if len(data) >= 5:
                        _, type_val = struct.unpack('!IB', data[:5])
                        if type_val == TYPE_SYN:
                            print(f"New client: {addr}")
                            rudp = RUDPConnection(sock, addr)
                            rudp.send_packet(0, TYPE_ACK)
                            
                            while True:
                                # Ждем команду 300 секунд (5 минут)
                                req = rudp.recv_reliable_data(timeout=300.0)
                                
                                if req is None: 
                                    print("Client idle timeout (300s).")
                                    break 
                                if not handle_request(rudp, req): 
                                    break
                            print("Session ended.")
                except OSError: pass
        except KeyboardInterrupt: break
        except Exception as e: print(f"Server Error: {e}")
    sock.close()

if __name__ == '__main__':
    start_server()