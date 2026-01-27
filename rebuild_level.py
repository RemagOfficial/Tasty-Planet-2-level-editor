"""
rebuild_level.py - Level Round-Trip Verification Tool

This helper script verifies that the level parser can correctly read AND write level files
by performing a complete round-trip conversion:
    1. Read a binary level file and convert it to JSON (using read_level.py)
    2. Write the JSON back to a binary file (using write_level.py)
    3. Compare or use the rebuilt file to verify data integrity

This is crucial for testing because:
- It validates that read_level.py correctly extracts all data from the binary format
- It validates that write_level.py correctly encodes all data back to binary format
- It ensures no data is lost or corrupted during the conversion process
- It helps catch bugs in either the reading or writing implementation

Usage:
    python rebuild_level.py <level.bin>

Example:
    python rebuild_level.py levels/dino5.bin

The script will:
- Create a JSON file (e.g., dino5_data.json) containing the parsed level data
- Create a rebuilt binary file (e.g., dino5(1).bin or similar to avoid overwriting)
- Prompt whether to clean up the temporary JSON file

If both read and write operations work correctly, the rebuilt binary file should
function identically to the original when used in the game.
"""

import sys
import subprocess
from pathlib import Path

def main():
    """Main function to orchestrate the level rebuild verification process."""
    # Parse command-line arguments
    if len(sys.argv) < 2:
        print("Usage: python rebuild_level.py <level.bin>")
        sys.exit(1)

    # Validate that the input file exists
    input_path = Path(sys.argv[1]).resolve()
    if not input_path.exists():
        print(f"Error: File {input_path} does not exist.")
        sys.exit(1)

    # STEP 1: Determine temporary JSON path
    # read_level.py creates a file named "<level_name>_data.json" in the current directory
    json_path = Path(f"{input_path.stem}_data.json")

    # STEP 2: Run read_level.py to convert binary to JSON
    # This validates that the reading functionality works correctly
    print(f"--- Running read_level.py on {input_path.name} ---")
    subprocess.run([sys.executable, "read_level.py", str(input_path)], check=True)

    # STEP 3: Determine output binary path for the rebuilt file
    # We want to avoid overwriting the original file, so we'll add a suffix if needed
    output_path = Path(input_path.name)
    
    # Collision detection: if the output name would overwrite the input or an existing file,
    # add a numeric suffix like (1), (2), etc.
    if output_path.resolve() == input_path.resolve() or output_path.exists():
        counter = 1
        while True:
            candidate = Path(f"{input_path.stem}({counter}).bin")
            # Ensure the candidate doesn't exist AND isn't the same as the input file
            if not candidate.exists() and candidate.resolve() != input_path.resolve():
                output_path = candidate
                break
            counter += 1

    # STEP 4: Run write_level.py to convert JSON back to binary
    # This validates that the writing functionality works correctly
    print(f"\n--- Running write_level.py to create {output_path} ---")
    subprocess.run([sys.executable, "write_level.py", str(json_path), str(output_path)], check=True)

    print(f"\nDone! Rebuilt level is at: {output_path.resolve()}")

    # STEP 5: Cleanup prompt
    # Ask the user if they want to delete the intermediate JSON file
    # (You may want to keep it for inspection or debugging)
    choice = input(f"\nDo you want to clean up (delete) the temporary file {json_path.name}? (y/n): ").lower()
    if choice == 'y':
        json_path.unlink()
        print(f"Deleted {json_path.name}")
    else:
        print(f"Kept {json_path.name}")

if __name__ == "__main__":
    main()
