import xml.etree.ElementTree as ET
import os
import re
import shutil
import sys
from datetime import datetime

class TPParser:
    def __init__(self, assets_path):
        self.assets_path = assets_path
        # Determine base directory for persist data (like backups)
        if getattr(sys, 'frozen', False):
            self.app_dir = os.path.dirname(sys.executable)
        else:
            # parser.py is in editor/, so root is parent
            self.app_dir = os.path.dirname(os.path.dirname(__file__))

        # graphics_path is just a hint now, we will search for files individually
        self.graphics_path = assets_path if os.path.exists(os.path.join(assets_path, "animationdefs.xml")) else os.path.join(assets_path, "graphics")
        self.imagemaps = {}
        self.tiledefs = {}
        self.entitydefs = {}
        self.animationdefs = {}

    def create_backup(self, file_path):
        """Creates a timestamped backup of a file in the workspace backups folder."""
        if not file_path or not os.path.exists(file_path): return
        try:
            # Workspace root backup folder
            backup_dir = os.path.join(self.app_dir, "backups")
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
            
            fname = os.path.basename(file_path)
            # Add timestamp to avoid overwriting a good backup with a bad one
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"{ts}_{fname}")
            shutil.copy2(file_path, backup_path)
            
            # Keep only last 10 backups for this specific filename to avoid bloat
            backups = sorted([f for f in os.listdir(backup_dir) if f.endswith(fname)], reverse=True)
            for old_b in backups[10:]:
                try: os.remove(os.path.join(backup_dir, old_b))
                except: pass
        except Exception as e:
            print(f"!! BACKUP ERROR: {e}")

    def get_attribs(self, tag_str):
        if not tag_str: return {}
        # Support keys with dots and unquoted values more broadly
        pattern = r'([\w:.-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s/>\t\n\r]+))'
        matches = re.findall(pattern, tag_str)
        attribs = {}
        for m in matches:
            key = m[0].lower()
            val = m[1] or m[2] or m[3] or ""
            attribs[key] = val
        return attribs

    def _get_tags(self, content, tag_name):
        """Highly lenient tag extractor with better boundary detection."""
        if not content: return
        
        # Pre-process: Strip comments to prevent false matches inside them
        if "<!" in content:
            content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
            
        pos = 0
        tag_lower = f"<{tag_name.lower()}"
        
        while True:
            start = content.lower().find(tag_lower, pos)
            if start == -1: break
            
            # Ensure it's not a partial match
            next_idx = start + len(tag_lower)
            # Support end-of-file as a boundary
            is_valid = True
            if next_idx < len(content):
                if content[next_idx] not in (' ', '>', '/', '\n', '\t', '\r'):
                    is_valid = False
            
            if not is_valid:
                pos = start + 1
                continue

            header_end = -1
            in_q, q_c = False, None
            for i in range(start + 1, len(content)):
                c = content[i]
                if c in ('"', "'"):
                    if not in_q: in_q, q_c = True, c
                    elif c == q_c: in_q = False
                elif c == '>' and not in_q:
                    header_end = i
                    break
            if header_end == -1: break
            
            header_text = content[start + 1 : header_end]
            name_len = len(tag_name)
            attr_text = header_text[name_len:]
            attributes = self.get_attribs(attr_text)
            
            if header_text.strip().endswith('/'):
                yield attributes, ""
                pos = header_end + 1
            else:
                # Find termination: </tag> OR next sibling <tag
                close_pat = f"</{tag_name.lower()}"
                next_close = content.lower().find(close_pat, header_end + 1)
                
                # Sibling check
                next_start = content.lower().find(tag_lower, header_end + 1)
                while next_start != -1:
                    nx_c_idx = next_start + len(tag_lower)
                    is_sibling = True
                    if nx_c_idx < len(content):
                        if content[nx_c_idx] not in (' ', '>', '/', '\n', '\t', '\r'):
                            is_sibling = False
                    
                    if is_sibling: break
                    next_start = content.lower().find(tag_lower, next_start + 1)

                if next_close != -1 and (next_start == -1 or next_close < next_start):
                    inner = content[header_end + 1 : next_close]
                    c_end = content.find('>', next_close)
                    pos = (c_end + 1) if c_end != -1 else (next_close + len(close_pat))
                    yield attributes, inner
                elif next_start != -1:
                    inner = content[header_end + 1 : next_start]
                    pos = next_start
                    yield attributes, inner
                else:
                    inner = content[header_end + 1 :]
                    pos = len(content)
                    yield attributes, inner

    def _get_all_children(self, text):
        """Extracts all top-level child tags from a block of XML-like text, preserving unknowns."""
        if not text: return []
        # Strip comments
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        children = []
        pos = 0
        tag_start_pat = re.compile(r'<([a-zA-Z0-9_.-]+)')
        
        while pos < len(text):
            match = tag_start_pat.search(text, pos)
            if not match: break
            
            tag_name = match.group(1)
            start = match.start()
            
            # Find end of header >
            header_end = -1
            in_q, q_c = False, None
            for i in range(start + 1, len(text)):
                c = text[i]
                if c in ('"', "'"):
                    if not in_q: in_q, q_c = True, c
                    elif c == q_c: in_q = False
                elif c == '>' and not in_q:
                    header_end = i
                    break
            
            if header_end == -1:
                pos = start + 1
                continue
            
            header_text = text[start+1 : header_end]
            attributes = self.get_attribs(header_text[len(tag_name):])
            
            if header_text.strip().endswith('/'):
                children.append({'name': tag_name, 'attr': attributes, 'inner': None})
                pos = header_end + 1
            else:
                tag_lower = f"<{tag_name.lower()}"
                close_pat = f"</{tag_name.lower()}"
                next_close = text.lower().find(close_pat, header_end + 1)
                next_start = text.lower().find(tag_lower, header_end + 1)
                
                while next_start != -1:
                    nx_c_idx = next_start + len(tag_lower)
                    is_sibling = True
                    if nx_c_idx < len(text) and text[nx_c_idx] not in (' ', '>', '/', '\n', '\t', '\r'):
                        is_sibling = False
                    if is_sibling: break
                    next_start = text.lower().find(tag_lower, next_start + 1)
                
                if next_close != -1 and (next_start == -1 or next_close < next_start):
                    inner = text[header_end + 1 : next_close]
                    c_end = text.find('>', next_close)
                    children.append({'name': tag_name, 'attr': attributes, 'inner': inner})
                    pos = (c_end + 1) if c_end != -1 else (next_close + len(close_pat))
                elif next_start != -1:
                    inner = text[header_end + 1 : next_start]
                    children.append({'name': tag_name, 'attr': attributes, 'inner': inner})
                    pos = next_start
                else:
                    inner = text[header_end + 1 :]
                    children.append({'name': tag_name, 'attr': attributes, 'inner': inner})
                    pos = len(text)
        return children

    def find_xml(self, filename):
        """Unified file finding logic across different installation styles."""
        # ONLY look in the active assets_path (Mod or Vanilla)
        if self.assets_path:
            # Priority 1: Mod graphics subfolder (Steam's usual spot)
            mod_graphics_path = os.path.join(self.assets_path, "graphics", filename)
            if os.path.exists(mod_graphics_path): return mod_graphics_path

            # Priority 2: Mod root
            mod_root_path = os.path.join(self.assets_path, filename)
            if os.path.exists(mod_root_path): return mod_root_path
            
        return None

    def parse_all(self):
        print(f"--- PARSER: Scanning XMLs (Assets: {self.assets_path}) ---")
        self.imagemaps.clear()
        self.tiledefs.clear()
        self.entitydefs.clear()
        self.animationdefs.clear()
        self.parse_imagemaps()
        self.parse_tiledefs()
        self.parse_entitydefs()
        self.parse_animationdefs()
        print(f"--- PARSER: Finished. Maps: {len(self.imagemaps)}, Entities: {len(self.entitydefs)}, Tiles: {len(self.tiledefs)} ---")

    def parse_imagemaps(self):
        file_path = self.find_xml("imagemaps.xml")
        if not file_path: return
        self.create_backup(file_path)
        print(f"   + Loading Maps: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
            for attr, inner in self._get_tags(content, "imagemap"):
                map_name = attr.get('name') or attr.get('id')
                filename = attr.get('filename')
                if not map_name or not filename: continue
                cells = {}; full_image = False; grid_info = None
                if inner:
                    if "<fullimagecell" in inner.lower(): full_image = True
                    for c_attr, _ in self._get_tags(inner, "cell"):
                        c_name = c_attr.get('name') or c_attr.get('id')
                        if c_name:
                            cells[c_name] = self._process_cell_attr(c_attr)
                            if '_list' not in cells: cells['_list'] = []
                            cells['_list'].append(cells[c_name])
                    for g_type in ["cellgrid", "cellgridpadded"]:
                        for g_attr, _ in self._get_tags(inner, g_type):
                            grid_info = {'type': g_type, 'attr': g_attr}; break
                        if grid_info: break
                self.imagemaps[map_name] = {'filename': filename, 'mask': attr.get('mask'), 'full_image': full_image or (not cells and not grid_info), 'cells': cells, 'grid': grid_info }
        except Exception as e: print(f"!! PARSER ERROR (imagemaps): {e}")

    def _process_cell_attr(self, attr):
        try:
            x = int(float(attr.get('x1', attr.get('x', 0))))
            y = int(float(attr.get('y1', attr.get('y', 0))))
            w = int(float(attr.get('w', 0)))
            h = int(float(attr.get('h', 0)))
            x2 = int(float(attr.get('x2', x + w)))
            y2 = int(float(attr.get('y2', y + h)))
            if w == 0: w = x2 - x
            if h == 0: h = y2 - y
            if w == 0: w = 256; h = 256
            return {'x': x, 'y': y, 'w': w, 'h': h, 'orig_w': int(float(attr.get('origwidth', 0))), 'orig_h': int(float(attr.get('origheight', 0)))}
        except: return {'x':0, 'y':0, 'w':256, 'h':256, 'orig_w':0, 'orig_h':0}

    def parse_tiledefs(self):
        file_path = self.find_xml("tiledefs.xml")
        if not file_path: return
        self.create_backup(file_path)
        print(f"   + Loading Tiles: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
            for attr, _ in self._get_tags(content, "tiledef"):
                name = attr.get('name') or attr.get('id')
                if name: self.tiledefs[name] = {'imagemap': attr.get('imagemap'), 'cell': attr.get('cell') or attr.get('imagemapcell'), 'animationdef': attr.get('animationdef')}
        except Exception as e: print(f"!! PARSER ERROR (tiles): {e}")

    def parse_entitydefs(self):
        file_path = self.find_xml("entitydefs.xml")
        if not file_path: return
        self.create_backup(file_path)
        print(f"   + Loading Entities: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
            for attr, inner in self._get_tags(content, "entitydef"):
                name = attr.get('name') or attr.get('id')
                if name:
                    intersects = []
                    if inner:
                        # Extract intersection shapes
                        for t_type in ['circle', 'rectangle', 'rotrect', 'rect', 'square']:
                            for t_attr, _ in self._get_tags(inner, t_type):
                                real_type = 'rect' if t_type != 'circle' else 'circle'
                                intersects.append({'type': real_type, 'attr': t_attr})
                    
                    # Safe conversion to float
                    def safe_f(v, default=1.0):
                        try:
                            if not v: return default
                            return float(v)
                        except: return default

                    self.entitydefs[name] = {
                        'imagemap': attr.get('imagemap'), 
                        'cell': attr.get('cell', attr.get('imagemapcell')), 
                        'animationdef': attr.get('animationdef'), 
                        'aspectratio': safe_f(attr.get('aspectratio')), 
                        'areacoverage': safe_f(attr.get('areacoverage')), 
                        'intersections': intersects 
                    }
        except Exception as e: print(f"!! PARSER ERROR (entities): {e}")

    def parse_animationdefs(self):
        file_path = self.find_xml("animationdefs.xml")
        if not file_path: return
        self.create_backup(file_path)
        print(f"   + Loading Animations: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
            for attr, inner in self._get_tags(content, "animationdef"):
                name = attr.get('name') or attr.get('id')
                if name:
                    imap = attr.get('imagemap')
                    frames = []
                    if inner:
                        for f_attr, _ in self._get_tags(inner, "frame"):
                            frames.append({'cell': f_attr.get('cell'), 'cellname': f_attr.get('cellname'), 'imagemap': f_attr.get('imagemap', imap), 'time': f_attr.get('time', "1.0")})
                    self.animationdefs[name] = {'looping': attr.get('looping') == 'true', 'time': float(attr.get('time', 1.0) if attr.get('time') else 1.0), 'frames': frames }
        except Exception as e: print(f"!! PARSER ERROR (animations): {e}")

    def sanitize_xml(self, content): return re.sub(r'&(?!(amp|lt|gt|apos|quot);)', '&amp;', content)

    def load_level(self, level_name):
        # Handle cases where level_name already has .xml extension
        base_name = level_name
        if not base_name.lower().endswith('.xml'):
            base_name += ".xml"
        
        # Priority 1: assets_path/levels/ (Actual game levels)
        file_path = os.path.join(self.assets_path, "levels", base_name)
        if not os.path.exists(file_path):
            # Priority 2: assets_path root
            file_path = os.path.join(self.assets_path, base_name)
            if not os.path.exists(file_path):
                return None
        
        try:
            self.create_backup(file_path)
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = self.sanitize_xml(f.read())
            
            # Find level root
            level_tags = list(self._get_tags(content, "level"))
            if not level_tags: return None
            l_attr, l_inner = level_tags[0]
            
            data = { 'properties': l_attr, 'goo': None, 'emitters': [], 'tilelayers': [], 'unhandled': [] }
            
            # Known tags we handle
            known = ['goo', 'emitter', 'tilelayers', 'tilelayer']
            
            for g_attr, _ in self._get_tags(l_inner, "goo"): data['goo'] = g_attr; break
            
            for e_attr, e_inner in self._get_tags(l_inner, "emitter"):
                e_attr['controllers'] = []
                if e_inner:
                    for c_attr, c_inner in self._get_tags(e_inner, "controller"):
                        c_attr['affects'], c_attr['dontaffects'], c_attr['pairs'] = [], [], []
                        if c_inner:
                            for a_attr, _ in self._get_tags(c_inner, "affect"): c_attr['affects'].append(a_attr)
                            for d_attr, _ in self._get_tags(c_inner, "dontaffect"): c_attr['dontaffects'].append(d_attr)
                            for p_attr, _ in self._get_tags(c_inner, "pair"): c_attr['pairs'].append(p_attr)
                        e_attr['controllers'].append(c_attr)
                    
                    # Support scheduledemit (list of points)
                    for _, sch_inner in self._get_tags(e_inner, "scheduledemit"):
                        if sch_inner:
                            e_attr['scheduledemit'] = []
                            for emit_attr, _ in self._get_tags(sch_inner, "emit"):
                                e_attr['scheduledemit'].append(emit_attr)
                    
                    for s in ['randomemit', 'left', 'right', 'top', 'bottom']:
                        for s_attr, _ in self._get_tags(e_inner, s): e_attr[s] = s_attr; break
                data['emitters'].append(e_attr)
            
            # Tilelayers (block)
            for tl_attr, tl_inner in self._get_tags(l_inner, "tilelayers"):
                if tl_inner:
                    for ly_attr, ly_inner in self._get_tags(tl_inner, "tilelayer"):
                        ly_attr['tiles'] = []
                        if ly_inner:
                            for t_attr, _ in self._get_tags(ly_inner, "tile"): ly_attr['tiles'].append(t_attr)
                        data['tilelayers'].append(ly_attr)
            
            # Tilelayer (direct)
            if not data['tilelayers']:
                for ly_attr, ly_inner in self._get_tags(l_inner, "tilelayer"):
                    ly_attr['tiles'] = []
                    if ly_inner:
                        for t_attr, _ in self._get_tags(ly_inner, "tile"): ly_attr['tiles'].append(t_attr)
                    data['tilelayers'].append(ly_attr)

            return data
        except Exception as e:
            print(f"!! PARSER ERROR (load level from {file_path}): {e}")
            return None

    def save_level(self, level_data, level_name):
        # Create backup before overwrite if file exists
        base_name = level_name if level_name.lower().endswith('.xml') else level_name + ".xml"
        save_path = os.path.join(self.assets_path, "levels", base_name)
        if not os.path.exists(os.path.dirname(save_path)):
            save_path = os.path.join(self.assets_path, base_name)
        
        if os.path.exists(save_path):
            self.create_backup(save_path)

        root = ET.Element('level', level_data['properties'])
        
        if level_data['goo']: ET.SubElement(root, 'goo', level_data['goo'])
        for emitter in level_data['emitters']:
            e_elem = ET.SubElement(root, 'emitter')
            for k, v in emitter.items():
                if k not in ['controllers', 'randomemit', 'left', 'right', 'top', 'bottom', 'scheduledemit', 'unhandled']: e_elem.set(k, str(v))
            
            for ctrl in emitter['controllers']:
                c_elem = ET.SubElement(e_elem, 'controller')
                for k, v in ctrl.items():
                    if k not in ['affects', 'dontaffects', 'pairs', 'unhandled']: c_elem.set(k, str(v))
                
                for sub in ['affect', 'dontaffect', 'pair']:
                    for item in ctrl.get(sub + 's', []): ET.SubElement(c_elem, sub, item)
            
            if emitter.get('randomemit'): ET.SubElement(e_elem, 'randomemit', emitter['randomemit'])
            
            if emitter.get('scheduledemit'):
                sch_elem = ET.SubElement(e_elem, 'scheduledemit')
                for em in emitter['scheduledemit']:
                    ET.SubElement(sch_elem, 'emit', em)

            for side in ['left', 'right', 'top', 'bottom']:
                if emitter.get(side): ET.SubElement(e_elem, side, emitter[side])
        if level_data['tilelayers']:
            tl_elem = ET.SubElement(root, 'tilelayers')
            for layer in level_data['tilelayers']:
                ly_elem = ET.SubElement(tl_elem, 'tilelayer')
                for k, v in layer.items():
                    if k != 'tiles': ly_elem.set(k, str(v))
                for t in layer['tiles']: ET.SubElement(ly_elem, 'tile', {k: str(v) for k, v in t.items()})
        tree = ET.ElementTree(root)
        ET.indent(tree, space="    ", level=0)
        tree.write(save_path, encoding='utf-8', xml_declaration=True)
        print(f"--- SAVED LEVEL: {save_path} ---")
        
        # Determine save location (Prioritize the active mod assets folder)
        base_name = level_name if level_name.lower().endswith(".xml") else f"{level_name}.xml"
        save_path = os.path.join(self.assets_path, "levels", base_name)
        
        # If the assets/levels folder doesn't exist, try root of assets
        if not os.path.exists(os.path.dirname(save_path)):
            save_path = os.path.join(self.assets_path, base_name)
            
        # Ensure we can actually write there
        try:
            tree.write(save_path, encoding="utf-8", xml_declaration=True)
            print(f"Level saved to: {save_path}")
        except Exception as e:
            print(f"!! SAVE ERROR: Could not save to {save_path}: {e}")
