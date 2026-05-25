import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sender.m3_merkle import build_merkle_tree, get_merkle_root

def print_merkle_tree(tree):
    """
    Prints a visual representation of the Merkle tree.
    """
    # Group nodes by level
    levels = {}
    for node_hash, node in tree.items():
        if node.level not in levels:
            levels[node.level] = []
        levels[node.level].append(node)
    
    max_level = max(levels.keys())
    
    print("\nMerkle Tree Visualization:")
    print("==========================")
    
    for level in range(max_level, -1, -1):
        print(f"\nLevel {level}:")
        # Sort by hash to maintain consistent output (optional)
        for node in sorted(levels[level], key=lambda x: x.hash):
            short_hash = node.hash[:8]
            if node.left_child and node.right_child:
                print(f"  [{short_hash}] -> ({node.left_child[:8]}, {node.right_child[:8]})")
            else:
                print(f"  [{short_hash}] (Leaf)")

if __name__ == "__main__":
    # Sample data: 3 chunks (will be padded to 4)
    chunks = [b"chunk1", b"chunk2", b"chunk3"]
    tree = build_merkle_tree(chunks)
    
    print(f"Number of nodes in tree: {len(tree)}")
    print(f"Root hash: {get_merkle_root(tree)}")
    
    print_merkle_tree(tree)
