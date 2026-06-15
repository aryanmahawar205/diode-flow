source deployment_env/bin/activate

# python3 sender_node.py \
#     --file "$1" \
#     --receiver-ip "$2" \
#     --security "${3:-standard}" \
#     --pps "${4:-50000}" \
#     --loss "${5:-0.0}" \
#     --port "${6:-20000}" \
#     --timeout "${7:-86400}"

sudo python sender_node.py \
  --file test_files/100MB.txt \
  --receiver-ip 10.21.3.X \
  --receiver-mac AA:BB:CC:DD:EE:FF \
  --interface enp3s0f1