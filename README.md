# Tasty-Planet-2-level-parser
A python script to parse level.bin files from Tasty Planet Back for Seconds

## About

This project provides scripts to parse and write level.bin files for Tasty Planet Back for Seconds. With both `read_level.py` and `write_level.py`, custom levels in Tasty Planet Back for Seconds are now fully possible! You can extract existing levels to JSON, modify them, and write them back to binary format, or create entirely new custom levels from scratch.

## Usage

### Reading Levels (read_level.py)

To parse a binary level file into JSON format, use the following command:

```bash
python read_level.py <level_file.bin>
```

#### Example

```bash
python read_level.py levels/dino5.bin
```

#### Output

The script will create a JSON file called `<level_file_name>_data.json` in the root of the scripts folder (the directory where you run the script).

For example, if you run:
```bash
python read_level.py levels/dino5.bin
```

The output file will be created as `dino5_data.json` in the current directory.

### Writing Levels (write_level.py)

To convert a JSON level file back into binary format, use the following command:

```bash
python write_level.py <level_data.json> [output.bin]
```

If you don't specify an output filename, the script will automatically create one with the `.bin_rebuilt` extension.

#### Example

```bash
python write_level.py dino5_data.json custom_level.bin
```

Or to use the default output filename:

```bash
python write_level.py dino5_data.json
```

This will create `dino5_data.bin_rebuilt` in the current directory.

#### Output

The script will write the binary level file to the specified output path (or `<input_file>.bin_rebuilt` if no output path is provided).

### Creating Custom Levels

To create a custom level for Tasty Planet Back for Seconds:

1. Extract an existing level to JSON:
   ```bash
   python read_level.py levels/dino5.bin
   ```

2. Edit the resulting `dino5_data.json` file to customize the level (modify entities, decorations, walls, paths, etc.)

3. Convert the modified JSON back to binary format with the **same filename** as the original level:
   ```bash
   python write_level.py dino5_data.json dino5.bin
   ```

4. Replace the original level file in your game's levels folder with your custom `dino5.bin` to use it in-game!

**Note:** Custom levels must match the filename of an existing vanilla level to work in-game. The custom level will replace the vanilla level when you play.

## Verbose Scripts

For debugging and advanced usage, verbose versions of both scripts are available. These scripts create detailed log files that track every byte read or written during the parsing/writing process.

### read_level_verbose.py

This is a verbose version of `read_level.py` that generates a detailed log file alongside the JSON output.

#### Usage

```bash
python read_level_verbose.py <level_file.bin>
```

#### Example

```bash
python read_level_verbose.py levels/dino5.bin
```

#### Output

In addition to creating the standard `<level_file_name>_data.json` file, this script also generates:
- `<level_file_name>_read_verbose.log` - A detailed log file containing:
  - Byte offsets (hex addresses) for every data structure
  - Raw byte values for each field read
  - Human-readable interpretations of the data
  - Timing information for the parsing process

This log file is invaluable for:
- Debugging level parsing issues
- Understanding the binary format structure
- Verifying that data is being read correctly
- Reverse engineering the level file format

### write_level_verbose.py

This is a verbose version of `write_level.py` that generates a detailed log file during the binary writing process.

#### Usage

```bash
python write_level_verbose.py <level_data.json>
```

#### Example

```bash
python write_level_verbose.py dino5_data.json
```

#### Output

This script creates:
- `<level_name>_rebuilt_verbose.bin` - The binary level file
- `<level_name>_rebuilt_verbose.log` - A detailed log file containing:
  - Byte offsets (hex addresses) where each data structure was written
  - Raw byte values written for each field
  - Human-readable descriptions of what was written
  - Timing information for the writing process

This log file is useful for:
- Debugging level writing issues
- Verifying the output binary matches expectations
- Comparing write logs with read logs to ensure round-trip accuracy
- Understanding how JSON data is converted back to binary format

### When to Use Verbose Scripts

Use the verbose scripts when:
- You encounter errors or unexpected behavior with level parsing/writing
- You're trying to understand the binary format structure in detail
- You need to verify that specific data is being read or written correctly
- You're developing new features or fixing bugs in the parser
- You want to compare the binary structure of different level files

For normal usage, the standard `read_level.py` and `write_level.py` scripts are sufficient and more performant.
