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

3. Convert the modified JSON back to binary format:
   ```bash
   python write_level.py dino5_data.json my_custom_level.bin
   ```

4. Place the resulting `my_custom_level.bin` file in your game's levels folder to use it!
