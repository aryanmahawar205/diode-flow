source deployment_env/bin/activate

python3 receiver_node.py \
    --port "${1:-20000}" \
    --timeout "${2:-86400}"