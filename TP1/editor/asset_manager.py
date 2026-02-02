import os
from PIL import Image, ImageTk

class AssetManager:
    def __init__(self, assets_path, parser):
        self.assets_path = assets_path
        self.parser = parser
        self.images = {} # Raw images (PIL Image)
        self.cells = {} # Individual cropped cells (PIL Image)
        self.tk_cache = {} # Cached Image elements for display
        self.image_files = {} # Master image paths mapping
        # Use root if graphics/ folder doesn't exist
        graphics_dir = os.path.join(assets_path, "graphics")
        self.graphics_path = graphics_dir if os.path.exists(graphics_dir) else assets_path
        self.graphics_mode = "new" # "new" or "old"

    def unload(self):
        """Releases all image resources to allow folder swapping on Windows."""
        for img in self.images.values():
            try: img.close()
            except: pass
        for cell in self.cells.values():
            try: cell.close()
            except: pass
        self.images.clear()
        self.cells.clear()
        self.tk_cache.clear()
        self.image_files.clear()
        
        import gc
        gc.collect() # Aggressively clean up any lingering handles

    def load_all_graphics(self):
        # Build master image dictionary
        self.image_files.clear()

        def scan_dir(root_dir, priority_name):
            if not os.path.exists(root_dir): return
            for root, dirs, files in os.walk(root_dir):
                for f in files:
                    full_p = os.path.normpath(os.path.join(root, f))
                    if not f.lower().endswith(('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.gif')):
                        continue
                    
                    rel_to_root = os.path.relpath(full_p, root_dir).replace("\\", "/")
                    fname_no_ext = os.path.splitext(f)[0]
                    rel_to_root_no_ext = os.path.splitext(rel_to_root)[0]

                    candidates = [
                        rel_to_root, rel_to_root_no_ext, f, fname_no_ext,
                        rel_to_root.replace("/", "\\"), rel_to_root_no_ext.replace("/", "\\")
                    ]
                    for key in candidates:
                        self.image_files[key] = full_p
                        self.image_files[key.lower()] = full_p

        # 1. Scan Vanilla/Base assets (Lowest priority)
        img_root = self.graphics_path
        if os.path.exists(img_root):
            # Define vanilla priority order
            primary = "newgraphics" if self.graphics_mode == "new" else "oldgraphics"
            secondary = "oldgraphics" if self.graphics_mode == "new" else "newgraphics"
            fallbacks = ["low", "high", "standard"]
            
            # Get internal folders
            all_dirs = [d for d in os.listdir(img_root) if os.path.isdir(os.path.join(img_root, d))]
            
            # Scan order (Bottom up)
            for d in fallbacks:
                scan_dir(os.path.join(img_root, d), d)
            scan_dir(os.path.join(img_root, secondary), secondary)
            scan_dir(img_root, ".") # Root graphics folder
            scan_dir(os.path.join(img_root, primary), primary)
            
            # Any other custom folders inside graphics
            for d in all_dirs:
                if d.lower() not in ([primary.lower(), secondary.lower()] + [f.lower() for f in fallbacks]):
                    scan_dir(os.path.join(img_root, d), d)

        # Match imagemaps to found files
        loaded_count = 0
        self.images.clear()
        self.cells.clear()
        self.tk_cache.clear()

        for map_name, map_info in self.parser.imagemaps.items():
            filename = map_info['filename']
            norm_filename = filename.replace("\\", "/").lower()
            img_path = self.image_files.get(filename) or self.image_files.get(norm_filename)
            
            if not img_path:
                name_strip = os.path.splitext(filename)[0].lower().replace("\\", "/")
                img_path = self.image_files.get(name_strip)

            if img_path:
                try:
                    with Image.open(img_path) as im:
                        im.load() # Force load into memory
                        img = im.convert("RGBA").copy() # Detach from file handle
                        
                    # Use existing mask logic...
                    mask_file = map_info.get('mask')
                    mask_path = None
                    if mask_file:
                        mf_norm = mask_file.replace("\\", "/").lower()
                        mask_path = self.image_files.get(mask_file) or self.image_files.get(mf_norm)
                    
                    if not mask_path:
                        mask_name = os.path.splitext(filename)[0].lower().replace("\\", "/") + "mask"
                        mask_path = self.image_files.get(mask_name)

                    if mask_path:
                        try:
                            with Image.open(mask_path) as mim:
                                mim.load()
                                mask_img = mim.convert('L').copy()
                                
                            if mask_img.size != img.size:
                                mask_img = mask_img.resize(img.size, Image.Resampling.LANCZOS)
                            r, g, b = img.split()[:3]
                            img = Image.merge("RGBA", (r, g, b, mask_img))
                            mask_img.close()
                        except: pass

                    self.images[map_name] = img
                    if map_info.get('full_image'):
                        self.cells[f"{map_name}:_idx_0"] = img
                    self.process_map_grid_and_cells(map_name, map_info, img)
                    loaded_count += 1
                except Exception as e:
                    print(f"!! ASSETS: Failed to load {img_path}: {e}")
            else:
                if loaded_count < 3:
                    print(f"?? ASSETS: Missing graphic for {map_name}: {filename}")

        print(f"--- ASSETS: Loaded {loaded_count}/{len(self.parser.imagemaps)} maps ---")

    def process_map_grid_and_cells(self, map_name, map_info, img):
        """Helper to stay organized while processing cells"""
        # Handle cellgrids and cellgridpadded
        grid_info = map_info.get('grid')
        if grid_info:
            try:
                g_type = grid_info['type']
                g_attr = grid_info['attr']
                gw = int(g_attr.get('width', 0))
                gh = int(g_attr.get('height', 0))
                num = int(g_attr.get('number', 0))
                
                if gw > 0 and gh > 0:
                    if g_type == 'cellgridpadded':
                        spacing = 1 
                        cols = (img.width + spacing) // (gw + spacing)
                        rows = (img.height + spacing) // (gh + spacing)
                        if num == 0: num = cols * rows
                        for i in range(num):
                            col = i % cols
                            row = i // cols
                            x = col * (gw + spacing)
                            y = row * (gh + spacing)
                            self.cells[f"{map_name}:_idx_{i}"] = img.crop((x, y, x + gw, y + gh))
                    else:
                        cols = img.width // gw
                        rows = img.height // gh
                        if num == 0: num = cols * rows
                        for i in range(num):
                            col = i % cols
                            row = i // cols
                            box = (col * gw, row * gh, (col + 1) * gw, (row + 1) * gh)
                            self.cells[f"{map_name}:_idx_{i}"] = img.crop(box)
            except: pass

        # Handle named and indexed cells
        for cell_name, cell_data in map_info['cells'].items():
            if cell_name == '_list': continue
            try:
                box = (cell_data['x'], cell_data['y'], 
                        cell_data['x'] + cell_data['w'], 
                        cell_data['y'] + cell_data['h'])
                self.cells[f"{map_name}:{cell_name}"] = img.crop(box)
            except: pass
        
        if '_list' in map_info['cells']:
            for idx, cell_data in enumerate(map_info['cells']['_list']):
                try:
                    box = (cell_data['x'], cell_data['y'], 
                            cell_data['x'] + cell_data['w'], 
                            cell_data['y'] + cell_data['h'])
                    self.cells[f"{map_name}:_idx_{idx}"] = img.crop(box)
                except: pass

    def get_cell_by_id(self, map_name, cell_id=None, cell_name=None):
        # Handle name resolution
        if not map_name and not cell_name: return None
        
        # Redirect for New Graphics mode: map goo1/goo2 to the consolidated newgoo0 sheet
        if self.graphics_mode == "new":
            if map_name in ["goo1", "goo2"] and cell_name is None:
                # Original goo1/2 have 4 cells each. 
                # newgoo0 has cells "newgoo1" through "newgoo8"
                base = 1 if map_name == "goo1" else 5
                try:
                    cell_idx = int(cell_id or 0)
                    map_name = "newgoo0"
                    cell_name = f"newgoo{base + cell_idx}"
                except:
                    pass
            elif map_name is None and cell_name:
                cname_str = str(cell_name).lower()
                if "newgoo" in cname_str or "eyelid" in cname_str or "goopupil" in cname_str or "gooeye" in cname_str:
                    # These are all high-res assets usually stored in newgoo0
                    map_name = "newgoo0" if self.graphics_mode == "new" else None
                elif "goo" in cname_str:
                    map_name = "newgoo0" if self.graphics_mode == "new" else "goo1"

        # If map_name is still missing, search for the cell_name in all loaded maps
        if not map_name and cell_name:
            for m_name in self.images.keys():
                if f"{m_name}:{cell_name}" in self.cells:
                    map_name = m_name
                    break
            if not map_name:
                # Still not found? Maybe the cell_name IS the map name
                if cell_name in self.images:
                    return self.images[cell_name]
                return None

        # Determine the effective name and key
        target_name = cell_name if cell_name else cell_id
        
        # If it's a full image map, always return the whole image
        map_info = self.parser.imagemaps.get(map_name)
        if map_info and map_info.get('full_image'):
            img = self.images.get(map_name)
            if img: return img

        # Try specific key formats
        keys_to_try = [
            f"{map_name}:{target_name}",
            f"{map_name}:_idx_{target_name}",
        ]
        
        # If the target name is a number, also try explicit index
        try:
            val = int(target_name)
            keys_to_try.append(f"{map_name}:_idx_{val}")
        except: pass

        for k in keys_to_try:
            if k in self.cells:
                return self.cells[k]

        # Final fallback - index 0
        idx0 = f"{map_name}:_idx_0"
        if idx0 in self.cells:
            return self.cells[idx0]
            
        img = self.images.get(map_name)
        if not img:
            print(f"DEBUG: Missing both cell {target_name} and image sheet {map_name}")
        return img

    def get_tile_image(self, tile_name, elapsed_time=0):
        tile_def = self.parser.tiledefs.get(tile_name)
        if not tile_def: return None
        
        imagemap_name = tile_def.get('imagemap')
        # Check both 'cell' and 'imagemapcell'
        cell_index = tile_def.get('cell', tile_def.get('imagemapcell'))
        anim_name = tile_def.get('animationdef')
        
        if anim_name:
            return self.get_animation_frame(anim_name, elapsed_time)
        
        if imagemap_name:
            return self.get_cell_by_id(imagemap_name, cell_index)
        return None

    def get_entity_image(self, entity_name, elapsed_time=0):
        # Override for the player character which use specific animations
        if entity_name == "Player":
            return self.get_animation_frame("goo", elapsed_time)
            
        ent_def = self.parser.entitydefs.get(entity_name)
        if not ent_def: return None
        
        imagemap_name = ent_def.get('imagemap')
        # Check both 'cell' and 'imagemapcell'
        cell_index = ent_def.get('cell', ent_def.get('imagemapcell'))
        anim_name = ent_def.get('animationdef')
        
        if anim_name:
            return self.get_animation_frame(anim_name, elapsed_time)
            
        if imagemap_name:
            return self.get_cell_by_id(imagemap_name, cell_index)
        return None

    def get_animation_first_frame(self, anim_name):
        return self.get_animation_frame(anim_name, 0)

    def get_animation_frame(self, anim_name, elapsed_time):
        # Handle graphics mode variants (e.g., "goo" -> "newgoo" in new mode)
        effective_anim = anim_name
        if self.graphics_mode == "new" and not anim_name.startswith("new"):
            if f"new{anim_name}" in self.parser.animationdefs:
                effective_anim = f"new{anim_name}"
        
        anim = self.parser.animationdefs.get(effective_anim)
        if not anim:
            # Fallback for newgoo2
            if effective_anim == "newgoo2":
                anim = self.parser.animationdefs.get("newgoo")
            if not anim: return None
        
        frames = anim.get('frames', [])
        if not frames: return None
        
        def safe_float(v, default=1.0):
            try: return float(v) if v is not None else default
            except: return default

        # Calculate total duration
        # If the animationdef has a 'time' attribute, it usually defines the TOTAL loop time.
        total_duration = safe_float(anim.get('time'), 0.0)
        
        frame_weights = [safe_float(f.get('time')) for f in frames]
        total_weight = sum(frame_weights)
        if total_weight <= 0: total_weight = 1.0
        
        # If no total duration specified, use sum of weights as seconds
        if total_duration <= 0:
            total_duration = total_weight

        # Decide current time in loop
        if anim.get('looping', True):
            t = elapsed_time % total_duration
        else:
            t = min(elapsed_time, total_duration - 0.001)
            
        # Map current time into weight space
        time_to_weight = total_weight / total_duration
        target_weight = t * time_to_weight
        
        acc = 0
        for f in frames:
            dur = safe_float(f.get('time'))
            if acc + dur >= target_weight:
                return self.get_cell_by_id(f.get('imagemap') or anim.get('imagemap'), f.get('cell'), f.get('cellname'))
            acc += dur
            
        # Fallback to last frame
        f = frames[-1]
        return self.get_cell_by_id(f.get('imagemap') or anim.get('imagemap'), f.get('cell'), f.get('cellname'))

    def get_tk_image(self, pil_img, scale=1.0, angle=0.0, flipx=False, flipy=False, alpha=1.0, tint=(1.0, 1.0, 1.0), transpose_v=False):
        if not pil_img: return None
        
        # Normalize inputs
        angle = float(angle or 0) % 360
        flipx = str(flipx).lower() == 'true'
        flipy = str(flipy).lower() == 'true'
        alpha = float(alpha if alpha is not None else 1.0)
        
        # Ensure tint is a tuple
        if not isinstance(tint, tuple): tint = (1.0, 1.0, 1.0)

        key = (id(pil_img), scale, angle, flipx, flipy, alpha, tint, transpose_v)
        if key in self.tk_cache:
            return self.tk_cache[key]
            
        temp_img = pil_img.copy()
        
        # Optional vertical flip (used for tiles to align with world space)
        if transpose_v:
            temp_img = temp_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        
        # Apply alpha and tint if needed
        if alpha < 1.0 or tint != (1.0, 1.0, 1.0):
            if temp_img.mode != 'RGBA':
                temp_img = temp_img.convert('RGBA')
            
            r, g, b, a = temp_img.split()
            # Apply tint to RGB
            if tint != (1.0, 1.0, 1.0):
                r = r.point(lambda i: int(i * tint[0]))
                g = g.point(lambda i: int(i * tint[1]))
                b = b.point(lambda i: int(i * tint[2]))
            
            # Apply alpha to A
            if alpha < 1.0:
                a = a.point(lambda i: int(i * alpha))
            
            temp_img = Image.merge('RGBA', (r, g, b, a))

        # Order of operations: Flip (local mirror) then Rotate (world orient)
        if flipx:
            temp_img = temp_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if flipy:
            temp_img = temp_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            
        if angle != 0:
            # TP1 uses Clockwise rotation (Rotate CCW by -angle in PIL)
            temp_img = temp_img.rotate(-angle, resample=Image.Resampling.BILINEAR, expand=True)

        # 3. Resize (Scaling)
        if scale != 1.0:
            w, h = temp_img.size
            resample = Image.Resampling.NEAREST if scale < 0.2 else Image.Resampling.BILINEAR
            temp_img = temp_img.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
            
        tk_img = ImageTk.PhotoImage(temp_img)
        self.tk_cache[key] = tk_img
        return tk_img

    def clear_tk_cache(self):
        self.tk_cache.clear()
