import struct
import math
import sys
import re
import json
from pathlib import Path

DEBUG_ENABLED = False

def find_next_lowercase_string(f):
    """Searches for a 4-byte little-endian length followed by a lowercase/underscore string."""
    current_pos = f.tell()
    # Read a chunk to scan
    chunk_size = 4096
    while True:
        pos = f.tell()
        data = f.read(chunk_size)
        if not data:
            break
        
        # Look for potential length prefix + lowercase string
        # A simple heuristic: find [length][char][char][char] where char is printable
        for i in range(len(data) - 8):
            try:
                length = struct.unpack('<I', data[i:i+4])[0]
                if 3 <= length <= 64:
                    # Check if next 'length' bytes are printable lowercase/digit/underscore
                    potential_name = data[i+4:i+4+length]
                    if len(potential_name) == length:
                        if all(0x20 <= b <= 0x7E for b in potential_name): # printable
                            name_str = potential_name.decode('ascii', errors='ignore').rstrip('\x00')
                            if re.match(r'^[a-z0-9_]+$', name_str):
                                return pos + i
            except Exception:
                continue
        
        # If not found, move forward but keep some overlap
        f.seek(pos + chunk_size - 64)
        if f.tell() >= f_size: break
    return -1

def find_next_decoration_block(f):
    """Searches for what looks like a decoration count followed by a decoration type."""
    current_pos = f.tell()
    data = f.read(1000) # search ahead a bit
    if len(data) >= 5:
        for i in range(len(data) - 5):
            count = struct.unpack('<I', data[i:i+4])[0]
            if count < 10000:
                dtype = data[i+4]
                if dtype <= 1:
                    # Check if the next byte after dtype looks reasonable?
                    # This is just a guess
                    return current_pos + i
    f.seek(current_pos)
    return -1

# Check for CLI argument
if len(sys.argv) < 2:
    print("Usage: python read_level.py <level_file>")
    print("Example: python read_level.py levels/dino5.bin")
    sys.exit(1)

input_path = Path(sys.argv[1])
if input_path.suffix.lower() == '.bin':
    bin_file = input_path
else:
    bin_file = input_path.with_suffix('.bin')

if not bin_file.exists():
    print(f"Error: File not found: {bin_file}")
    sys.exit(1)

output_file = Path(f"{input_path.stem}_data.json")
max_string_len = 1_000_000

with open(bin_file, 'rb') as f:
    # Get file size
    f.seek(0, 2)  # Seek to end
    f_size = f.tell()
    f.seek(0)  # Seek back to start
    
    # First two int32 values
    first_int32_bytes = f.read(4)
    first_int32 = struct.unpack('<i', first_int32_bytes)[0]

    second_int32_bytes = f.read(4)
    second_int32 = struct.unpack('<i', second_int32_bytes)[0]

    # Strings array based on second_int32 (tile type count)
    strings = []
    for _ in range(second_int32):
        length_bytes = f.read(4)
        if len(length_bytes) < 4:
            break
        string_length = struct.unpack('<i', length_bytes)[0]

        if string_length < 0 or string_length > max_string_len:
            print(f"WARNING: {bin_file.name} tile string length {string_length} out of bounds; stopping string parsing")
            break

        string_bytes = f.read(string_length)
        if len(string_bytes) < string_length:
            break
        try:
            string_value = string_bytes.decode('ascii').rstrip('\x00')
        except Exception:
            string_value = f"<binary data: {string_bytes.hex()}>"

        strings.append((string_length, string_value))

    # Layer count int32
    layer_bytes = f.read(4)
    layer_count = None
    if len(layer_bytes) == 4:
        layer_count = struct.unpack('<i', layer_bytes)[0]

    layers = []
    max_reasonable_count = 100000
    stop_due_to_entity_bool = False
    if layer_count and layer_count > 0:
        for layer_idx in range(layer_count):
            layer = {'layer': layer_idx + 1}
            layer['wall_count'] = None
            layer['path_count'] = None
            layer['entity_count'] = None
            layer['decoration_count'] = None
            layer['entities'] = []
            layer['walls'] = []
            layer['paths'] = []
            layer['decorations'] = []

            # Wall count int32 (per layer)
            wall_bytes = f.read(4)
            if len(wall_bytes) == 4:
                wall_count = struct.unpack('<i', wall_bytes)[0]
                layer['wall_count'] = wall_count
            else:
                wall_count = 0

            # Wall entries
            walls = []
            actual_wall_count = 0
            if wall_count and wall_count > 0:
                wall_start_pos = f.tell()
                if DEBUG_ENABLED:
                    print(f"DEBUG: Layer {layer_idx+1} wall parsing starts at position {wall_start_pos} (0x{wall_start_pos:X}), wall_count={wall_count}")

                for wall_idx in range(wall_count):
                    wall = {}
                    
                    # pos_x, pos_y, unknown1, unknown2 (four doubles)
                    pos_bytes = f.read(32)
                    if len(pos_bytes) < 32:
                        print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} position/unknown bytes short at position {f.tell()}")
                        break
                    pos_x, pos_y, width, length = struct.unpack('<dddd', pos_bytes)
                    wall['pos_x'] = pos_x
                    wall['pos_y'] = pos_y
                    wall['position'] = (pos_x, pos_y)
                    wall['width'] = width
                    wall['length'] = length
                    
                    # wall_type_name (length-prefixed string)
                    wall_type_strlen_bytes = f.read(4)
                    if len(wall_type_strlen_bytes) < 4:
                        print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} type_strlen bytes short at position {f.tell()}")
                        break
                    wall_type_strlen = struct.unpack('<i', wall_type_strlen_bytes)[0]
                    if wall_type_strlen < 0 or wall_type_strlen > 1000:
                        print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} type_strlen {wall_type_strlen} out of bounds at position {f.tell()-4}")
                        break
                    wall_type_bytes = f.read(wall_type_strlen)
                    if len(wall_type_bytes) < wall_type_strlen:
                        print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} type string bytes short at position {f.tell()}")
                        break
                    try:
                        wall['wall_type_name'] = wall_type_bytes.decode('ascii').rstrip('\x00')
                    except Exception:
                        wall['wall_type_name'] = f"<binary: {wall_type_bytes.hex()}>"
                    
                    # no_shapes_flag (uint8)
                    no_shapes_b = f.read(1)
                    if not no_shapes_b:
                        print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} no_shapes_flag byte missing at position {f.tell()}")
                        break
                    no_shapes_flag = no_shapes_b[0]
                    wall['has_shapes_flag'] = no_shapes_flag
                    wall['shapes'] = []
                    
                    # ShapeDefs block (conditional - if no_shapes_flag == 0, shapes follow)
                    if no_shapes_flag == 0:
                        # shape_count (int32)
                        shape_count_bytes = f.read(4)
                        if len(shape_count_bytes) < 4:
                            print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape_count bytes short at position {f.tell()}")
                            break
                        shape_count = struct.unpack('<i', shape_count_bytes)[0]
                        wall['shape_count'] = shape_count
                        
                        if shape_count < 0 or shape_count > 10000:
                            print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape_count {shape_count} out of bounds at position {f.tell()-4}")
                            break
                        
                        # For each shape
                        for shape_idx in range(shape_count):
                            shape = {}
                            
                            # shape type_name (length-prefixed string)
                            shape_type_strlen_bytes = f.read(4)
                            if len(shape_type_strlen_bytes) < 4:
                                print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape {shape_idx+1} type_strlen bytes short at position {f.tell()}")
                                break
                            shape_type_strlen = struct.unpack('<i', shape_type_strlen_bytes)[0]
                            if shape_type_strlen < 0 or shape_type_strlen > 1000:
                                print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape {shape_idx+1} type_strlen {shape_type_strlen} out of bounds at position {f.tell()-4}")
                                break
                            shape_type_bytes = f.read(shape_type_strlen)
                            if len(shape_type_bytes) < shape_type_strlen:
                                print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape {shape_idx+1} type string bytes short at position {f.tell()}")
                                break
                            try:
                                shape_type_name = shape_type_bytes.decode('ascii').rstrip('\x00')
                                shape['shape_type_name'] = shape_type_name
                            except Exception:
                                shape['shape_type_name'] = f"<binary: {shape_type_bytes.hex()}>"
                                shape_type_name = ""
                            
                            # Shape data depends on type
                            if shape_type_name == "Circle":
                                # center_x, center_y, radius (3 doubles)
                                circle_bytes = f.read(24)
                                if len(circle_bytes) < 24:
                                    print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape {shape_idx+1} circle data short at position {f.tell()}")
                                    break
                                center_x, center_y, radius = struct.unpack('<ddd', circle_bytes)
                                shape['data'] = {
                                    'type': 'Circle',
                                    'center_x': center_x,
                                    'center_y': center_y,
                                    'radius': radius
                                }
                            else:
                                # ConPoly: num_vertices + vertices array
                                num_vert_bytes = f.read(4)
                                if len(num_vert_bytes) < 4:
                                    print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape {shape_idx+1} num_vertices bytes short at position {f.tell()}")
                                    break
                                num_vertices = struct.unpack('<i', num_vert_bytes)[0]
                                if num_vertices < 0 or num_vertices > 100000:
                                    print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape {shape_idx+1} num_vertices {num_vertices} out of bounds at position {f.tell()-4}")
                                    break
                                
                                vertices = []
                                for vert_idx in range(num_vertices):
                                    vert_bytes = f.read(16)  # 2 doubles
                                    if len(vert_bytes) < 16:
                                        print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} shape {shape_idx+1} vertex {vert_idx+1} bytes short at position {f.tell()}")
                                        break
                                    vx, vy = struct.unpack('<dd', vert_bytes)
                                    vertices.append((vx, vy))
                                
                                shape['data'] = {
                                    'type': 'ConPoly',
                                    'num_vertices': num_vertices,
                                    'vertices': vertices
                                }
                            
                            wall['shapes'].append(shape)
                    
                    # reserved at the end (int32)
                    reserved_bytes = f.read(4)
                    if len(reserved_bytes) < 4:
                        print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} reserved bytes short at position {f.tell()}")
                        break
                    wall['reserved'] = struct.unpack('<i', reserved_bytes)[0]
                    
                    # wall_id comes AFTER all wall data (int32)
                    wall_id_bytes = f.read(4)
                    if len(wall_id_bytes) < 4:
                        print(f"WARNING: Layer {layer_idx+1} wall {wall_idx+1} wall_id bytes short at position {f.tell()}")
                        break
                    wall['wall_id'] = struct.unpack('<i', wall_id_bytes)[0]
                    
                    walls.append(wall)
                    actual_wall_count += 1
                    if DEBUG_ENABLED:
                        print(f"DEBUG: Layer {layer_idx+1} wall {wall_idx+1} parsed successfully, position now {f.tell()} (0x{f.tell():X})")
            layer['walls'] = walls
            if actual_wall_count > 0 and actual_wall_count < wall_count:
                print(f"INFO: Layer {layer_idx+1} only parsed {actual_wall_count} walls (wall_count was {wall_count})")

            # Path count int32 (per layer)
            path_count_bytes = f.read(4)
            path_count = None
            if len(path_count_bytes) == 4:
                path_count = struct.unpack('<i', path_count_bytes)[0]
                if path_count < 0 or path_count > max_reasonable_count:
                    print(f"WARNING: {bin_file.name} layer {layer_idx+1} path_count {path_count} out of bounds; skipping paths")
                    path_count = None
            layer['path_count'] = path_count

            # Paths
            paths = []
            if path_count and path_count > 0 and path_count <= max_reasonable_count:
                path_start_pos = f.tell()
                if DEBUG_ENABLED:
                    print(f"DEBUG: Layer {layer_idx+1} path parsing starts at position {path_start_pos} (0x{path_start_pos:X}), path_count={path_count}")
                
                for path_idx in range(path_count):
                    path = {}
                    
                    # path_name (length-prefixed string)
                    path_name_strlen_bytes = f.read(4)
                    if len(path_name_strlen_bytes) < 4:
                        print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} name_strlen bytes short at position {f.tell()}")
                        break
                    path_name_strlen = struct.unpack('<i', path_name_strlen_bytes)[0]
                    if path_name_strlen < 0 or path_name_strlen > 1000:
                        print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} name_strlen {path_name_strlen} out of bounds at position {f.tell()-4}")
                        break
                    path_name_bytes = f.read(path_name_strlen)
                    if len(path_name_bytes) < path_name_strlen:
                        print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} name string bytes short at position {f.tell()}")
                        break
                    try:
                        path['path_name'] = path_name_bytes.decode('ascii').rstrip('\x00')
                    except Exception:
                        path['path_name'] = f"<binary: {path_name_bytes.hex()}>"
                    
                    # position (2 doubles: x, y)
                    pos_bytes = f.read(16)
                    if len(pos_bytes) < 16:
                        print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} position bytes short at position {f.tell()}")
                        break
                    pos_x, pos_y = struct.unpack('<dd', pos_bytes)
                    path['position'] = (pos_x, pos_y)
                    
                    # extent_x_guess, extent_y_guess (2 doubles)
                    unknown_bytes = f.read(16)
                    if len(unknown_bytes) < 16:
                        print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} unknown bytes short at position {f.tell()}")
                        break
                    extent_x_guess, extent_y_guess = struct.unpack('<dd', unknown_bytes)
                    path['extent_x_guess'] = extent_x_guess
                    path['extent_y_guess'] = extent_y_guess
                    
                    # path_flag (uint8)
                    path_flag_bytes = f.read(1)
                    if not path_flag_bytes:
                        print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} path_flag byte missing at position {f.tell()}")
                        break
                    path_flag = path_flag_bytes[0]
                    path['path_flag'] = path_flag
                    
                    # Optional path_data (if path_flag == 1)
                    if path_flag == 1:
                        # point_count (int32)
                        point_count_bytes = f.read(4)
                        if len(point_count_bytes) < 4:
                            print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} point_count bytes short at position {f.tell()}")
                            break
                        point_count = struct.unpack('<i', point_count_bytes)[0]
                        if point_count < 0 or point_count > 10000:
                            print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} point_count {point_count} out of bounds at position {f.tell()-4}")
                            break
                        path['point_count'] = point_count
                        
                        # SplinePoint array
                        spline_points = []
                        for pt_idx in range(point_count):
                            # Each SplinePoint has 3 Vector2d (6 doubles total)
                            spline_bytes = f.read(48)  # 6 doubles * 8 bytes
                            if len(spline_bytes) < 48:
                                print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} spline point {pt_idx+1} bytes short at position {f.tell()}")
                                break
                            p0_x, p0_y, p1_x, p1_y, p2_x, p2_y = struct.unpack('<dddddd', spline_bytes)
                            spline_points.append({
                                'p0': (p0_x, p0_y),
                                'p1': (p1_x, p1_y),
                                'p2': (p2_x, p2_y)
                            })
                        path['spline_points'] = spline_points
                    else:
                        path['point_count'] = None
                        path['spline_points'] = []
                    
                    # internal_id_guess (int32)
                    some_int_bytes = f.read(4)
                    if len(some_int_bytes) < 4:
                        print(f"WARNING: Layer {layer_idx+1} path {path_idx+1} internal_id_guess bytes short at position {f.tell()}")
                        break
                    path['internal_id_guess'] = struct.unpack('<i', some_int_bytes)[0]
                    
                    paths.append(path)
                    if DEBUG_ENABLED:
                        print(f"DEBUG: Layer {layer_idx+1} path {path_idx+1} parsed successfully, position now {f.tell()} (0x{f.tell():X})")
            layer['paths'] = paths

            # Entity count int32 (per layer)
            entity_count_bytes = f.read(4)
            entity_count = None
            if len(entity_count_bytes) == 4:
                entity_count = struct.unpack('<i', entity_count_bytes)[0]
                if entity_count < 0 or entity_count > max_reasonable_count:
                    print(f"WARNING: {bin_file.name} layer {layer_idx+1} entity_count {entity_count} out of bounds; skipping entities")
                    entity_count = None
            layer['entity_count'] = entity_count

            entities = []
            if entity_count and entity_count > 0 and entity_count <= max_reasonable_count:
                lastEntPosX = 0.0
                lastEntPosY = 0.0
                lastPriority = 0
                
                ent_start_pos = f.tell()
                if DEBUG_ENABLED:
                    print(f"DEBUG: Layer {layer_idx+1} entity parsing starts at file position {ent_start_pos} (0x{ent_start_pos:X}), entity_count={entity_count}")

                for ent_idx in range(entity_count):
                    try:
                        # Resync heuristic: check if we are at a valid name header
                        pre_name_pos = f.tell()
                        header_bytes = f.read(4)
                        if len(header_bytes) == 4:
                            sl = struct.unpack('<i', header_bytes)[0]
                            is_likely_name = False
                            if 2 < sl < 128:
                                test_name = f.read(sl)
                                # Broad check: is it printable ascii and lowercase?
                                if all(32 <= b <= 126 or b == 0 for b in test_name):
                                    # Check for lowercase letters or underscore
                                    if any(b'a' <= bytes([b]) <= b'z' or b == ord('_') for b in test_name):
                                        is_likely_name = True
                                f.seek(pre_name_pos + 4) # back to after length
                            
                            if not is_likely_name:
                                if DEBUG_ENABLED:
                                    print(f"DEBUG: Entity {ent_idx+1} desync at {pre_name_pos} (0x{pre_name_pos:X}), searching...")
                                f.seek(pre_name_pos + 1)
                                found_sync = False
                                for _ in range(10000): # Larger range
                                    p = f.tell()
                                    b4 = f.read(4)
                                    if len(b4) < 4: break
                                    sl2 = struct.unpack('<i', b4)[0]
                                    if 2 < sl2 < 128:
                                        nb = f.read(sl2)
                                        if all(32 <= b <= 126 or b == 0 for b in nb):
                                            if any(b'a' <= bytes([b]) <= b'z' or b == ord('_') for b in nb):
                                                if DEBUG_ENABLED:
                                                    print(f"DEBUG: Found resync at {p} (0x{p:X}): {nb}")
                                                f.seek(p)
                                                found_sync = True
                                                break
                                    f.seek(p + 1)
                                if not found_sync:
                                    raise Exception("Could not resync entity")
                            else:
                                f.seek(pre_name_pos) # normal
                        else:
                            raise Exception("EOF reached while reading entity header")

                        ent = {'index': ent_idx + 1}

                        # Entity type string (length-prefixed)
                        type_strlen_bytes = f.read(4)
                        if len(type_strlen_bytes) < 4:
                            break
                        type_strlen = struct.unpack('<i', type_strlen_bytes)[0]
                        type_string_bytes = f.read(type_strlen)
                        if len(type_string_bytes) < type_strlen:
                            break
                        try:
                            ent['type'] = type_string_bytes.decode('ascii').rstrip('\x00')
                        except Exception:
                            ent['type'] = f"<binary: {type_string_bytes.hex()}>"

                        # Delta position (accumulated)
                        pos_bytes = f.read(8)
                        if len(pos_bytes) < 8:
                            break
                        dx, dy = struct.unpack('<ii', pos_bytes)
                        lastEntPosX += dx
                        lastEntPosY += dy
                        ent['dx'] = dx
                        ent['dy'] = dy
                        ent['position'] = (lastEntPosX * 0.01, lastEntPosY * 0.01)

                        # field_158, field_15c
                        field_bytes = f.read(8)
                        if len(field_bytes) < 8:
                            break
                        field_158, field_15c = struct.unpack('<ii', field_bytes)
                        ent['field_158'] = field_158
                        ent['field_15c'] = field_15c

                        # vec_x_raw, vec_y_raw (scaled 0.01)
                        vec_bytes = f.read(8)
                        if len(vec_bytes) < 8:
                            break
                        vec_x_raw, vec_y_raw = struct.unpack('<ii', vec_bytes)
                        ent['vec'] = {"raw": [vec_x_raw, vec_y_raw], "scaled": [round(vec_x_raw * 0.01, 4), round(vec_y_raw * 0.01, 4)]}

                        # field_250_raw, field_90_raw (scaled 0.01)
                        field2_bytes = f.read(8)
                        if len(field2_bytes) < 8:
                            break
                        field_250_raw, rot_raw = struct.unpack('<ii', field2_bytes)
                        ent['field_250'] = {"raw": field_250_raw, "scaled": round(field_250_raw * 0.01, 4)}
                        ent['rotation'] = {"raw": rot_raw, "scaled": round(rot_raw * 0.01, 4)}

                        # has_box
                        has_box_b = f.read(1)
                        if not has_box_b:
                            break
                        has_box = has_box_b[0]
                        ent['has_box'] = has_box

                        if has_box != 0:
                            box_bytes = f.read(20)  # 4 int32 enabled + 4 int32 a,b,c,d
                            if len(box_bytes) < 20:
                                break
                            box_enabled = struct.unpack('<i', box_bytes[0:4])[0]
                            box_a, box_b, box_c, box_d = struct.unpack('<iiii', box_bytes[4:20])
                            ent['box'] = {
                                'enabled': box_enabled,
                                'bounds': [box_a, box_b, box_c, box_d]
                            }
                        else:
                            ent['box'] = None

                        # Color RGBA
                        color_bytes = f.read(4)
                        if len(color_bytes) < 4:
                            break
                        ent['color'] = {"rgba": list(color_bytes)}

                        # mass (double)
                        # The mass double follows directly after the color.
                        # Do not align to 8-byte boundaries as it causes desyncs.
                        mass_bytes = f.read(8)
                        if len(mass_bytes) < 8:
                            break
                        ent['mass'] = struct.unpack('<d', mass_bytes)[0]

                        # priority_delta
                        prio_bytes = f.read(4)
                        if len(prio_bytes) < 4:
                            break
                        prio_delta = struct.unpack('<i', prio_bytes)[0]
                        lastPriority += prio_delta
                        ent['priority_delta'] = prio_delta
                        ent['priority'] = lastPriority

                        # Sequential flags and blocks
                        has_move_bytes = f.read(4)
                        if len(has_move_bytes) < 4: raise Exception("Short read for has_move")
                        has_move = struct.unpack('<i', has_move_bytes)[0]
                        ent['has_move_direction'] = has_move
                        
                        if has_move == 1:
                            if DEBUG_ENABLED:
                                print(f"DEBUG: Parsing move_direction at 0x{f.tell():X}")
                            v01_b = f.read(16)
                            if len(v01_b) < 16: raise Exception("Short read for move v0, v1")
                            v0, v1 = struct.unpack('<dd', v01_b)

                            f0_b = f.read(4)
                            if len(f0_b) < 4: raise Exception("Short read for move flag0")
                            flag0 = struct.unpack('<i', f0_b)[0]
                            
                            v27_b = f.read(48)
                            if len(v27_b) < 48: raise Exception("Short read for move v2-v7")
                            v2, v3, v4, v5, v6, v7 = struct.unpack('<dddddd', v27_b)
                            
                            ent['move_direction'] = {
                                'v0': v0, 'v1': v1, 'flag0': flag0,
                                'v2': v2, 'v3': v3, 'v4': v4,
                                'v5': v5, 'v6': v6, 'v7': v7
                            }
                            if DEBUG_ENABLED:
                                print(f"DEBUG: move_direction success at 0x{f.tell():X}")
                        else:
                            ent['move_direction'] = None
                        
                        has_path_bytes = f.read(4)
                        if len(has_path_bytes) < 4: raise Exception("Short read for has_path")
                        has_path = struct.unpack('<i', has_path_bytes)[0]
                        ent['has_path_follow'] = has_path

                        if has_path == 1:
                            if DEBUG_ENABLED:
                                print(f"DEBUG: Parsing path_follow at 0x{f.tell():X}")
                            v01_b = f.read(16)
                            if len(v01_b) < 16: raise Exception("Short read for path v0, v1")
                            v0, v1 = struct.unpack('<dd', v01_b)

                            f0_b = f.read(4)
                            if len(f0_b) < 4: raise Exception("Short read for path flag0")
                            flag0 = struct.unpack('<i', f0_b)[0]

                            v23_b = f.read(16) # 2 doubles: v2, v3
                            if len(v23_b) < 16: raise Exception("Short read for path v2, v3")
                            v2, v3 = struct.unpack('<dd', v23_b)

                            sl_bytes = f.read(4)
                            if len(sl_bytes) < 4: raise Exception("Short read for path name length")
                            sl = struct.unpack('<i', sl_bytes)[0]
                            path_name_bytes = f.read(sl)
                            if len(path_name_bytes) < sl: raise Exception("Short read for path name string")
                            path_name = path_name_bytes.decode('ascii', errors='ignore').rstrip('\x00')

                            f1_b = f.read(4)
                            if len(f1_b) < 4: raise Exception("Short read for path flag1")
                            flag1 = struct.unpack('<i', f1_b)[0]

                            mode_b = f.read(4)
                            if len(mode_b) < 4: raise Exception("Short read for path mode")
                            mode = struct.unpack('<i', mode_b)[0]

                            v4_b = f.read(8)
                            if len(v4_b) < 8: raise Exception("Short read for path v4")
                            v4 = struct.unpack('<d', v4_b)[0]

                            ent['path_follow'] = {
                                'v0': v0, 'v1': v1, 'flag0': flag0,
                                'v2': v2, 'v3': v3,
                                'path_name': path_name,
                                'flag1': flag1, 'mode': mode, 'v4': v4
                            }
                            if DEBUG_ENABLED:
                                print(f"DEBUG: path_follow success at 0x{f.tell():X}")
                        else:
                            ent['path_follow'] = None

                        has_emitter_bytes = f.read(4)
                        if len(has_emitter_bytes) < 4: raise Exception("Short read for has_emitter")
                        has_emitter = struct.unpack('<i', has_emitter_bytes)[0]
                        ent['has_emitter'] = has_emitter

                        # emitter_data initialization with 0s for reserved and end_marker
                        emitter_data = {
                            'has_data': has_emitter,
                            'reserved': 0,
                            'end_marker': 0
                        }
                        
                        if has_emitter == 1:
                            # 11 doubles (88 bytes)
                            emitter_doubles_bytes = f.read(88)
                            if len(emitter_doubles_bytes) < 88:
                                raise Exception("Short read for emitter doubles")
                            
                            vals = struct.unpack('<ddddddddddd', emitter_doubles_bytes)
                            emitter_data.update({
                                'v0': vals[0], 'v1': vals[1], 'v2': vals[2], 'v3': vals[3],
                                'v4': vals[4], 'v5': vals[5], 'v6': vals[6], 'v7': vals[7],
                                'v8': vals[8], 'v9': vals[9], 'v10': vals[10]
                            })
                            
                            # "end_marker and reserved are the last 2 ints of emitters"
                            # These follow only if an emitter is present in Layer 4 (index 3)
                            if layer_idx >= 3:
                                tail_bytes = f.read(8)
                                if len(tail_bytes) < 8:
                                    raise Exception("Short read for entity tail")
                                res_val, end_val = struct.unpack('<ii', tail_bytes)
                                emitter_data['reserved'] = res_val
                                emitter_data['end_marker'] = end_val
                                
                        ent['emitter'] = emitter_data

                        entities.append(ent)
                        if DEBUG_ENABLED:
                            print(f"DEBUG: Entity {ent_idx+1} ({ent['type']}) parsed successfully at position {f.tell()} (0x{f.tell():X})")
                    except Exception as e:
                        if DEBUG_ENABLED:
                            print(f"DEBUG: Error parsing entity {ent_idx+1} at position {f.tell()} (0x{f.tell():X}): {e}")
                        continue
                
            layer['entities'] = entities

            # Decoration count int32 (per layer)
            decoration_count_bytes = f.read(4)
            decoration_count = None
            if len(decoration_count_bytes) == 4:
                decoration_count = struct.unpack('<i', decoration_count_bytes)[0]
                if decoration_count < 0 or decoration_count > max_reasonable_count:
                    print(f"WARNING: {bin_file.name} layer {layer_idx+1} decoration_count {decoration_count} out of bounds; skipping decorations")
                    decoration_count = None
            layer['decoration_count'] = decoration_count

            # Decorations
            decorations = []
            if decoration_count and decoration_count > 0 and decoration_count <= max_reasonable_count:
                lastCell = -1
                lastPosX = 0.0
                lastPosY = 0.0
                lastPriority = 0

                for deco_idx in range(decoration_count):
                    deco = {'index': deco_idx + 1}

                    deco_type_b = f.read(1)
                    if not deco_type_b:
                        break
                    deco_type = deco_type_b[0]
                    deco['type'] = deco_type

                    if deco_type == 0x02:
                        deco['type_info'] = 'string'
                        strlen_bytes = f.read(4)
                        if len(strlen_bytes) < 4:
                            break
                        strlen = struct.unpack('<i', strlen_bytes)[0]
                        if strlen < 0 or strlen > 10000:
                            break
                        sbytes = f.read(strlen)
                        if len(sbytes) < strlen:
                            break
                        try:
                            deco['string'] = sbytes.decode('ascii').rstrip('\x00')
                        except Exception:
                            deco['string'] = f"<binary: {sbytes.hex()}>"
                        lastCell = -1
                    elif deco_type == 0x01:
                        deco['type_info'] = 'cell'
                        cell_bytes = f.read(4)
                        if len(cell_bytes) < 4:
                            break
                        lastCell = struct.unpack('<i', cell_bytes)[0]
                        deco['cell'] = lastCell
                    else:
                        deco['type_info'] = 'reuse'
                        if deco_type != 0:
                            lastCell = -1  # invalid type -> force no cell link

                    # Position offsets (two int32, accumulated)
                    off_bytes = f.read(8)
                    if len(off_bytes) < 8:
                        break
                    off_x, off_y = struct.unpack('<ii', off_bytes)
                    pos_x = (off_x + lastPosX) * 0.01
                    pos_y = (off_y + lastPosY) * 0.01
                    deco['offsets'] = (off_x, off_y)
                    deco['position'] = (pos_x, pos_y)
                    lastPosX += off_x
                    lastPosY += off_y

                    # Size / scale (int32)
                    size_bytes = f.read(4)
                    if len(size_bytes) < 4:
                        break
                    size_raw = struct.unpack('<i', size_bytes)[0]
                    deco['size'] = {"raw": size_raw, "scaled": round(size_raw * 0.01, 4)}

                    # Extra flag
                    extra_flag_b = f.read(1)
                    if not extra_flag_b:
                        break
                    extra_flag = extra_flag_b[0]
                    deco['extra_flag'] = extra_flag

                    handled_special = False
                    if extra_flag == 0:
                        deco['extra_bools'] = (0, 0)
                        deco['extra_ints'] = (0, 0, 0, 0)
                    else:
                        # Observed extra layout when flag != 0 (e.g., dino5 deco 139):
                        # bool byte x2, 4 x int32, size_override (int32), unknown (int32), color (4 bytes), width/height (2 x int32), priority delta (int32)
                        b1 = f.read(1)
                        b2 = f.read(1)
                        if len(b1) < 1 or len(b2) < 1:
                            break
                        deco['extra_bools'] = (b1[0], b2[0])

                        ints_bytes = f.read(16)
                        if len(ints_bytes) < 16:
                            break
                        i1, i2, i3, i4 = struct.unpack('<iiii', ints_bytes)
                        deco['extra_ints'] = (i1, i2, i3, i4)

                        size_override_bytes = f.read(4)
                        if len(size_override_bytes) < 4:
                            break
                        size_override_raw = struct.unpack('<i', size_override_bytes)[0]
                        deco['size_override'] = {"raw": size_override_raw, "scaled": round(size_override_raw * 0.01, 4)}

                        extra_unknown_bytes = f.read(2)
                        if len(extra_unknown_bytes) < 2:
                            break
                        deco['extra_unknown'] = struct.unpack('<h', extra_unknown_bytes)[0]

                        color_bytes = f.read(4)
                        if len(color_bytes) < 4:
                            break
                        deco['color_rgba'] = list(color_bytes)

                        wh_bytes = f.read(8)
                        if len(wh_bytes) < 8:
                            break
                        width_raw, height_raw = struct.unpack('<ii', wh_bytes)
                        deco['dimensions'] = {
                            "raw": [width_raw, height_raw],
                            "scaled": [round(width_raw * 0.01, 4), round(height_raw * 0.01, 4)],
                            "radius": round(0.5 * math.hypot(width_raw * 0.01, height_raw * 0.01), 4)
                        }

                        priority_bytes = f.read(4)
                        if len(priority_bytes) < 4:
                            break
                        delta = struct.unpack('<i', priority_bytes)[0]
                        lastPriority += delta
                        deco['priority'] = {"delta": delta, "total": lastPriority}
                        handled_special = True

                    # Cell pair reference comes from a table; no bytes consumed
                    deco['cell_ref'] = None

                    if handled_special:
                        decorations.append(deco)
                        continue

                    # Color RGBA (4 bytes; appears to be byte channels, not floats)
                    color_bytes = f.read(4)
                    if len(color_bytes) < 4:
                        break
                    deco['color_rgba'] = list(color_bytes)

                    # Width / height (int32 each)
                    wh_bytes = f.read(8)
                    if len(wh_bytes) < 8:
                        break
                    width_raw, height_raw = struct.unpack('<ii', wh_bytes)
                    deco['dimensions'] = {
                        "raw": [width_raw, height_raw],
                        "scaled": [round(width_raw * 0.01, 4), round(height_raw * 0.01, 4)],
                        "radius": round(0.5 * math.hypot(width_raw * 0.01, height_raw * 0.01), 4)
                    }

                    # Priority delta (int32)
                    priority_bytes = f.read(4)
                    if len(priority_bytes) < 4:
                        break
                    delta = struct.unpack('<i', priority_bytes)[0]
                    lastPriority += delta
                    deco['priority'] = {"delta": delta, "total": lastPriority}

                    deco['last_cell'] = lastCell
                    decorations.append(deco)

            layer['decorations'] = decorations
            layers.append(layer)

            if stop_due_to_entity_bool:
                break
# Prepare data for JSON output
def clean_data(obj):
    """Recursively removes None values and rounds floats for cleaner JSON."""
    if isinstance(obj, float):
        val = round(obj, 4)
        return int(val) if val == int(val) else val
    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            if v is None: continue
            # Omit redundant empty/zero noise
            if k in ('extra_bools', 'extra_ints') and isinstance(v, (list, tuple)) and all(x == 0 for x in v):
                continue
            if k == 'extra_flag' and v == 0:
                continue
            new_dict[k] = clean_data(v)
        return new_dict
    if isinstance(obj, (list, tuple)):
        return [clean_data(x) for x in obj]
    return obj

output_data = clean_data({
    "dummy": first_int32,
    "tileTypeCount": second_int32,
    "tileTypes": [{"length": length, "value": s} for length, s in strings],
    "layerCount": layer_count,
    "layers": layers
})

# Write output as proper JSON
with open(output_file, 'w') as out:
    json_str = json.dumps(output_data, indent=2)
    
    # Target specific fields for single-lining (targeted compaction)
    target_keys = [
        'move_direction', 'emitter', 'vec', 'color', 'position', 'offsets', 'extra_bools', 
        'extra_ints', 'spline_points', 'vertices', 'box', 'bounds', 'dimensions', 
        'priority', 'size', 'rgba', 'color_rgba', 'p0', 'p1', 'p2', 'uv', 'uvs', 
        'rotation', 'pivot', 'scale', 'uv_offset', 'uv_scale', 'data', 'size_override',
        'field_250', 'path_follow', 'view_box', 'render_box', 'shapes'
    ]
    
    for key in target_keys:
        search_pos = 0
        while True:
            # Find the next occurrence of the key followed by an opening bracket/brace
            pattern = r'"' + key + r'":\s*([\[\{])'
            match = re.search(pattern, json_str[search_pos:])
            if not match:
                break
            
            # Identify the actual start of the data block in the full string
            block_start = search_pos + match.start(1)
            opener = match.group(1)
            closer = ']' if opener == '[' else '}'
            
            # Find the balanced closing char
            depth = 0
            block_end = -1
            for i in range(block_start, len(json_str)):
                if json_str[i] == opener:
                    depth += 1
                elif json_str[i] == closer:
                    depth -= 1
                    if depth == 0:
                        block_end = i
                        break
            
            if block_end != -1:
                original_content = json_str[block_start : block_end + 1]
                if key == 'spline_points':
                    # Compact each point object individually, but keep the array multi-line
                    compacted = re.sub(r'\{[^{}]+\}', lambda m: re.sub(r'\s+', ' ', m.group(0)), original_content, flags=re.DOTALL)
                else:
                    # Compact whitespaces within the block completely
                    compacted = re.sub(r'\s+', ' ', original_content).strip()
                
                json_str = json_str[:block_start] + compacted + json_str[block_end + 1:]
                # Move search position forward past the new compacted block
                search_pos = block_start + len(compacted)
            else:
                search_pos = block_start + 1
                
    out.write(json_str)

print(f"Processed {bin_file.name}")
print(f"Tile type count: {second_int32}")
print(f"Layer count: {len(layers)}")

total_walls = sum(l.get('wall_count', 0) or 0 for l in layers)
total_paths = sum(l.get('path_count', 0) or 0 for l in layers)
total_entities = sum(l.get('entity_count', 0) or 0 for l in layers)
total_decorations = sum(l.get('decoration_count', 0) or 0 for l in layers)

print(f"Wall count: {total_walls}")
print(f"Path count: {total_paths}")
print(f"Entity count: {total_entities}")
print(f"Decoration count: {total_decorations}")
print(f"Results written to: {output_file}")
