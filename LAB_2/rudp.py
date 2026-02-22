import socket
import struct
import select
import time

PACKET_SIZE = 4096
HEADER_FMT = '!IB'
HEADER_SIZE = struct.calcsize(HEADER_FMT)
WINDOW_SIZE = 16
ACK_TIMEOUT = 0.3
MAX_RETRIES = 20

TYPE_DATA = 0
TYPE_ACK = 1
TYPE_SYN = 2
TYPE_FIN = 3

class RUDPConnection:
    def __init__(self, sock, addr=None):
        self.sock = sock
        self.addr = addr
        self.sock.setblocking(0)
        
    def flush(self):
        try:
            while True:
                data, _ = self.sock.recvfrom(65536)
        except (BlockingIOError, OSError):
            pass

    def send_packet(self, seq, type_val, data=b''):
        try:
            header = struct.pack(HEADER_FMT, seq, type_val)
            self.sock.sendto(header + data, self.addr)
        except (BlockingIOError, OSError):
            pass

    def _wait_ack(self, expected_ack_seq):
        start = time.time()
        while time.time() - start < ACK_TIMEOUT:
            try:
                ready = select.select([self.sock], [], [], 0.01)
                if ready[0]:
                    data, addr = self.sock.recvfrom(65536)
                    if self.addr and addr != self.addr: continue
                    if len(data) < HEADER_SIZE: continue
                    
                    seq, type_val = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                    if type_val == TYPE_ACK: return seq
                    if type_val == TYPE_FIN: return -2 
            except (BlockingIOError, OSError): pass
        return -1

    def send_reliable_data(self, data_source):
        self.flush()
        if isinstance(data_source, bytes):
            chunks = [data_source[i:i+PACKET_SIZE] for i in range(0, len(data_source), PACKET_SIZE)]
            if not chunks: chunks = [b'']
        else: raise ValueError("Only bytes allowed")

        base = 0
        next_seq = 0
        retries = 0

        while base < len(chunks):
            while next_seq < base + WINDOW_SIZE and next_seq < len(chunks):
                self.send_packet(next_seq, TYPE_DATA, chunks[next_seq])
                next_seq += 1
            
            ack = self._wait_ack(base)
            
            if ack >= base:
                base = ack + 1
                retries = 0
            elif ack == -2: raise ConnectionResetError("Connection closed by peer")
            else:
                retries += 1
                if retries > MAX_RETRIES: raise ConnectionResetError("Max retries exceeded")
                next_seq = base

    def recv_reliable_data(self, timeout=None):
        expected_seq = 0
        received_chunks = {}
        start_wait = time.time()
        
        while True:
            if timeout is not None and (time.time() - start_wait > timeout):
                return None

            try:
                ready = select.select([self.sock], [], [], 0.1)
                if not ready[0]: continue
                
                data, addr = self.sock.recvfrom(65536)
                
                # --- ЛОГИКА ПЕРЕХВАТА СЕССИИ ---
                if len(data) >= HEADER_SIZE:
                    seq, type_val = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                    
                    # Если пришел SYN (новый клиент или реконнект старого)
                    if type_val == TYPE_SYN:
                        # Переключаемся на этого клиента
                        self.addr = addr
                        self.send_packet(0, TYPE_ACK)
                        # Сбрасываем состояние приема
                        expected_seq = 0
                        received_chunks = {}
                        start_wait = time.time()
                        continue
                # -------------------------------

                if self.addr is None: self.addr = addr
                if addr != self.addr: continue
                
                if len(data) < HEADER_SIZE: continue
                seq, type_val = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                payload = data[HEADER_SIZE:]
                
                if type_val == TYPE_FIN:
                    return b'' # Сигнал о закрытии

                if type_val == TYPE_DATA:
                    if timeout is not None: start_wait = time.time()
                    
                    if seq == expected_seq:
                        received_chunks[seq] = payload
                        expected_seq += 1
                        self.send_packet(expected_seq - 1, TYPE_ACK)
                        
                        if payload.endswith(b'\n'):
                             return b''.join(received_chunks[i] for i in sorted(received_chunks.keys()))
                    elif seq < expected_seq:
                        self.send_packet(expected_seq - 1, TYPE_ACK)
            except (BlockingIOError, OSError): pass

    def send_file_bulk(self, filename):
        self.flush()
        base = 0
        next_seq = 0
        file_buffer = {}
        f = open(filename, 'rb')
        retries = 0
        
        try:
            while True:
                while next_seq < base + WINDOW_SIZE:
                    if next_seq not in file_buffer:
                        chunk = f.read(PACKET_SIZE)
                        if not chunk: 
                            file_buffer[next_seq] = None
                            break
                        file_buffer[next_seq] = chunk
                    if file_buffer[next_seq] is None: break
                    
                    self.send_packet(next_seq, TYPE_DATA, file_buffer[next_seq])
                    next_seq += 1
                
                if base == next_seq and (base in file_buffer and file_buffer[base] is None):
                    break
                if base == next_seq and not file_buffer: 
                    break

                ack = self._wait_ack(base)
                
                if ack >= base:
                    for i in range(base, ack + 1):
                        if i in file_buffer: del file_buffer[i]
                    base = ack + 1
                    retries = 0
                else:
                    retries += 1
                    if retries > MAX_RETRIES:
                        raise ConnectionResetError("File transfer timed out")
                    next_seq = base
        finally:
            f.close()
            for _ in range(5): 
                self.send_packet(next_seq, TYPE_FIN)
                time.sleep(0.01)

    def recv_stream_to_file(self, filename, expected_size):
        self.flush()
        expected_seq = 0
        bytes_written = 0
        last_activity = time.time()
        
        f = open(filename, 'wb')
        try:
            while bytes_written < expected_size:
                if time.time() - last_activity > 2.0:
                    self.send_packet(max(0, expected_seq - 1), TYPE_ACK)
                    last_activity = time.time()

                try:
                    ready = select.select([self.sock], [], [], 1.0)
                    if not ready[0]: 
                        if time.time() - last_activity > 10.0:
                            raise ConnectionResetError("Receive timeout")
                        continue 
                    
                    packet, addr = self.sock.recvfrom(65536)
                    if addr != self.addr: continue
                    if len(packet) < HEADER_SIZE: continue
                    
                    seq, type_val = struct.unpack(HEADER_FMT, packet[:HEADER_SIZE])
                    payload = packet[HEADER_SIZE:]
                    
                    if type_val == TYPE_FIN: break
                    
                    if type_val == TYPE_DATA:
                        last_activity = time.time()
                        if seq == expected_seq:
                            f.write(payload)
                            bytes_written += len(payload)
                            expected_seq += 1
                            self.send_packet(expected_seq - 1, TYPE_ACK)
                        elif seq < expected_seq:
                            self.send_packet(expected_seq - 1, TYPE_ACK)
                except (BlockingIOError, OSError): pass
        finally:
            f.close()