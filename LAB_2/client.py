import socket
import sys
import time
import os
from rudp import RUDPConnection, TYPE_SYN, TYPE_FIN

def connect_udp(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(0)
    try: s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024) # Еще больше буфер
    except: pass
    
    conn = RUDPConnection(s, (host, port))
    print(f"Connecting to {host}:{port}...")
    
    for _ in range(3):
        conn.send_packet(0, TYPE_SYN)
        # Маленькая пауза перед проверкой ACK для локальной сети
        time.sleep(0.1)
        # Проверяем неблокирующим чтением
        ack = conn._wait_ack_nonblocking() 
        if ack != -1:
            print("Connected!")
            return conn
    return None

def print_progress(current, total):
    """Оптимизированный вывод прогресса"""
    if total <= 0: return
    percent = (current / total) * 100
    
    if not hasattr(print_progress, 'last_time'):
        print_progress.last_time = 0
        
    # Обновляем экран не чаще 5 раз в секунду
    now = time.time()
    if now - print_progress.last_time > 0.2 or current == total:
        mb_curr = current / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        sys.stdout.write(f"\rDownloading: {percent:.1f}%  ({mb_curr:.0f}/{mb_total:.0f} MB)   ")
        sys.stdout.flush()
        print_progress.last_time = now

def do_download(conn, filename):
    conn.flush()
    print(f"Requesting {filename}...")
    conn.send_reliable_data(f"DOWNLOAD {filename}\n".encode())
    
    resp = conn.recv_reliable_data(timeout=5.0)
    if not resp:
        print("No response.")
        return
        
    msg = resp.decode().strip()
    if not msg.startswith('OK'):
        print(f"Server: {msg}")
        return
        
    try: filesize = int(msg.split()[1])
    except: return

    print(f"Size: {filesize/1024/1024:.2f} MB. Starting...")
    
    if hasattr(print_progress, 'last_time'): del print_progress.last_time
    
    conn.send_reliable_data(b"READY\n")
    
    start = time.time()
    try:
        conn.recv_stream_to_file(filename, filesize, progress_callback=print_progress)
        print() 
    except Exception as e:
        print(f"\nStopped: {e}")
    
    duration = time.time() - start
    
    if os.path.exists(filename):
        actual = os.path.getsize(filename)
        if actual == filesize:
            mbps = (actual * 8) / (duration * 1024 * 1024) if duration > 0 else 0
            print(f"Done! {duration:.2f}s. Speed: {mbps:.2f} Mbps")
        else:
            print(f"\nFAILED! {actual}/{filesize} bytes.")
    else:
        print("File creation failed.")

def main_loop(host, port):
    conn = connect_udp(host, port)
    if not conn:
        print("Connection failed.")
        return False

    try:
        while True:
            cmd = input("UDP> ").strip()
            if not cmd: continue
            
            if cmd.lower() in ('exit', 'quit'): break
                
            if cmd.lower().startswith('download'):
                parts = cmd.split()
                if len(parts) > 1: do_download(conn, parts[1])
                else: print("Usage: download <filename>")
            else:
                conn.send_reliable_data((cmd + "\n").encode())
                resp = conn.recv_reliable_data(timeout=2.0)
                if resp: print(resp.decode().strip())
                else: print("No response.")
                
    except (ConnectionResetError, socket.timeout):
        print("\nConnection lost.")
        return False 
    except KeyboardInterrupt:
        return True
    except Exception as e:
        print(f"\nError: {e}")
        return False
    finally:
        try: 
            conn.send_packet(0, TYPE_FIN)
            conn.sock.close()
        except: pass

    return True

def start_client():
    default_ip = "127.0.0.1"
    default_port = 9090
    
    host_in = input(f"Enter IP (default {default_ip}): ").strip()
    HOST = host_in if host_in else default_ip
    
    port_in = input(f"Enter Port (default {default_port}): ").strip()
    PORT = int(port_in) if port_in else default_port

    while True:
        if main_loop(HOST, PORT) is True: sys.exit(0)
        if input("Retry? (y/n): ").lower() != 'y': sys.exit(0)

if __name__ == '__main__':
    start_client()