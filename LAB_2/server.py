import socket
import os
import struct
import select
from rudp import RUDPConnection, TYPE_SYN, TYPE_ACK

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def handle_request(rudp, data):
    try:
        msg = data.decode('utf-8', errors='ignore').strip()
    except: return True
    
    if not msg: return True
    parts = msg.split()
    cmd = parts[0].upper()
    
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
        rudp.send_reliable_data(f"OK {size}\n".encode())
        
        confirm = rudp.recv_reliable_data(timeout=10.0)
        if confirm and b'READY' in confirm:
            rudp.send_file_bulk(filename)
        
    elif cmd == 'UPLOAD':
        rudp.send_reliable_data(b"ERROR Not implemented\n")
        
    elif cmd in ('EXIT', 'QUIT'):
        return False
    else:
        rudp.send_reliable_data(b"UNKNOWN COMMAND\n")
        
    return True

def start_server():
    default_ip = "0.0.0.0"
    default_port = 9090
    
    print(f"Detected Local IP: {get_local_ip()}")
    
    port_input = input(f"Enter Port (default {default_port}): ").strip()
    PORT = int(port_input) if port_input else default_port

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((default_ip, PORT))
    except Exception as e:
        print(f"Error binding to port: {e}")
        return

    sock.setblocking(0)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
    except: pass
    
    print(f"UDP Server listening on {default_ip}:{PORT}")
    
    while True:
        try:
            readable, _, _ = select.select([sock], [], [], 0.5)
            if readable:
                try:
                    data, addr = sock.recvfrom(1024)
                    if len(data) >= 5:
                        _, type_val = struct.unpack('!IB', data[:5])
                        if type_val == TYPE_SYN:
                            print(f"Client connected: {addr}")
                            rudp = RUDPConnection(sock, addr)
                            rudp.send_packet(0, TYPE_ACK)
                            
                            while True:
                                try:
                                    # Ждем команду 300 сек
                                    # Если придет SYN от другого, recv_reliable_data переключится сам
                                    req = rudp.recv_reliable_data(timeout=300.0)
                                    
                                    # Проверка: не переключился ли клиент "на лету"?
                                    if rudp.addr != addr:
                                        print(f"Session hijacked by new client: {rudp.addr}")
                                        addr = rudp.addr
                                        # Продолжаем цикл с новым адресом
                                        if req is None: continue 
                                        
                                    if req is None: 
                                        print("Client idle timeout.")
                                        break 
                                    if req == b'':
                                        print("Client sent FIN.")
                                        break
                                        
                                    if not handle_request(rudp, req): 
                                        break
                                except ConnectionResetError:
                                    break
                                except Exception:
                                    break
                                    
                            print(f"Client disconnected. Waiting for new...")
                except OSError: pass
        except KeyboardInterrupt:
            print("\nServer shutting down.")
            break
        except Exception as e:
            print(f"Server Error: {e}")
            
    sock.close()

if __name__ == '__main__':
    start_server()