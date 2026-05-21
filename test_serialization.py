import hmac
from data_diode.sender.m10_serializer import serialize_packet, deserialize_packet

class MockPacket:
    def __init__(self):
        self.transfer_id = "test-transfer"
        self.window_id = 0
        self.pass_id = 0
        self.packet_id = 1
        self.degree = 2
        self.seed = 12345
        self.data = b"hello world"

secret = b"S" * 32
pkt = MockPacket()

try:
    print("Testing serialization...")
    data = serialize_packet(pkt, secret)
    print(f"Serialized size: {len(data)} bytes")
    
    print("Testing deserialization...")
    recovered = deserialize_packet(data, secret)
    print("Success! Recovered transfer_id:", recovered.transfer_id)
    
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
