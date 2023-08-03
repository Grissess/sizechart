from xml.etree import ElementTree as ET
import argparse
import math
import glob
import traceback
import os

#import pygame_sdl2
#pygame_sdl2.import_as_pygame()
import pygame

NS = {
    'svg': 'http://www.w3.org/2000/svg',
    'xlink': 'http://www.w3.org/1999/xlink',
    'sizechart': 'urn:grissess:sizechart',
}

def ns(n, t):
    return f'{{{NS[n]}}}{t}'

CURSOR = '|'

def smoothscale_by(surf, scale):
    return pygame.transform.smoothscale(
        surf,
        tuple(int(i * scale) for i in surf.get_size())
    )

def steps(origin, width, bias = 0.25):
    step = 10 ** (int(math.log(width, 10) - bias))
    nearest = int(origin / step) * step
    x = nearest
    while x <= origin+width:
        yield x
        x += step

class Canvas:
    def __init__(self, disp, origin = (0.0, 0.0), scale=0.01):
        self.disp, self.origin, self._scale = disp, origin, scale
        self.cache = {}
        self.font = pygame.font.Font(None, 24)
        self.blits = 0

    @property
    def viewbox(self):
        w, h = self.disp.get_size()
        x, y = self.origin
        return pygame.Rect(x, y, w / self._scale, h / self._scale)

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, v):
        self._scale = v
        self.cache.clear()

    def map_scaled(self, p):
        return tuple(map(int, (i * self._scale for i in p)))

    def map_point(self, p):
        x, y = self.map_scaled(i - o for i, o in zip(p, self.origin))
        return x, self.disp.get_height() - y

    def unmap_scaled(self, p):
        return tuple(map(int, (i / self._scale for i in p)))

    def unmap_point(self, p):
        x, y = p
        y = self.disp.get_height() - y
        p = self.unmap_scaled((x, y))
        return tuple(i + o for i, o in zip(p, self.origin))

    def move(self, dx=0, dy=0):
        self.origin = tuple(i+o for i, o in zip(self.origin, (dx, dy)))

    def scale_into(self, scale, pos):
        # No part of this works and I don't know why
        # but it barely works, so here we go
        delta = tuple(i - o for i, o in zip(pos, self.origin))
        olds = self.scale
        self.scale *= scale
        newscale = self.scale * scale
        ds = newscale - olds
        pan = tuple(i * ds / self.scale / 2 for i in delta)
        print(f'scale_into: scale={scale} pos={pos} delta={delta} ds={ds} pan={pan}')
        self.move(*pan)

    def clear(self):
        self.disp.fill((0, 0, 0))

    def blit(self, surf, pos=(0, 0)):
        r = surf.get_rect()
        r.x, r.y = pos
        if not r.colliderect(self.viewbox):
            return
        self.blits += 1
        if surf not in self.cache:
            self.cache[surf] = smoothscale_by(surf, self._scale)
        target = self.cache[surf]
        x, y = self.map_point(pos)
        # put the origin in the bottom left (where it belongs), including of the source
        y -= target.get_height()
        #print(f'blit a {target.get_size()} surface to {(x, y)}')
        self.disp.blit(target, (x, y))

    def rect(self, r, color = pygame.Color(255, 255, 255, 255), width=1):
        pos, dim = (r.x, r.y), (r.w, r.h)
        x, y = self.map_point(pos)
        w, h = self.map_scaled(dim)
        r = pygame.Rect(0, 0, w, h)
        r.bottomleft = (x, y)
        #print(f'rect {pos} {dim} renders as {r}')
        pygame.draw.rect(self.disp, color, r, width)

    def line(self, a, b, color = pygame.Color(255, 255, 255, 255), width=1):
        ma = self.map_point(a)
        mb = self.map_point(b)
        pygame.draw.line(self.disp, color, ma, mb, width)

    def text(self, s, color = pygame.Color(255, 255, 255, 255)):
        return self.font.render(s, True, color)

    def text_scr(self, pos, s, color = pygame.Color(255, 255, 255, 255)):
        self.disp.blit(self.text(s, color), pos)

    def text_pt(self, pos, s, color = pygame.Color(255, 255, 255, 255)):
        self.text_scr(self.map_point(pos), s, color)

class Sprite:
    def __init__(self, surf, path, scale=1.0, olap = 0.75, y = 0.0, refy = None):
        self.surf, self.path, self._scale, self.olap, self.y = surf, path, scale, olap, y
        self._render = None
        self.refy = refy
        self.lastx = None

    @classmethod
    def from_element(cls, elem):
        path = elem.get('href', elem.get(ns('xlink', 'href')))
        try:
            surf = pygame.image.load(path)
        except FileNotFoundError:
            surf = pygame.Surface(
                int(element.get(ns('sizechart', 'origWidth'), 2)),
                int(element.get(ns('sizechart', 'origHeight'), 2)),
            )
            with pygame.PixelArray(surf) as pa:
                pa[::2, ::2] = pygame.Color(255, 0, 255, 255)
                pa[1::2, 1::2] = pygame.Color(255, 0, 255, 255)
        scale = float(elem.get(ns('sizechart', 'scale'), 1.0))
        olap = float(elem.get(ns('sizechart', 'overlap'), 0.75))
        y = float(elem.get(ns('sizechart', 'offsetY'), 0.0))
        ry = elem.get(ns('sizechart', 'referenceY'))
        if ry is not None:
            ry = float(ry)
        return cls(surf, path, scale, olap, y, ry)

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, v):
        self._scale = v
        self._render = None

    @property
    def render(self):
        if self._render is None:
            self._render = smoothscale_by(self.surf, self._scale)
        return self._render

    REF_COLOR = pygame.Color(255, 0, 255, 255)
    def draw(self, canv, x, app):
        self.lastx = x
        canv.blit(self.render, (x, self.y * self.scale))
        if self.refy is not None:
            y = self.scale * (self.refy + self.y)
            canv.line(
                (x, y), 
                (x + self.render.get_width(), y),
                self.REF_COLOR,
            )
            u = app.unit if app.real_units else 'px'
            dy = y
            if app.real_units:
                dy /= app.ppu
            s = canv.text(f'{dy:.3f}{u}', self.REF_COLOR)
            sx, sy = canv.map_point((x, y))
            canv.disp.blit(s, (sx, sy + 1))
        return x + self.render.get_width() * self.olap

    def box(self, canv, x, color=pygame.Color(255, 255, 255, 255)):
        canv.rect(
            pygame.Rect(x, self.scale * self.y, *self.render.get_size()),
            color,
        )

    @property
    def rect(self):
        if self.lastx is None:
            return
        r = self.render.get_rect()
        r.x = self.lastx
        r.y = self.scale * self.y
        print(f'spr rect {r}')
        return r

    def contains(self, cpt):
        return self.rect.collidepoint(cpt)

    def save(self, tb, vh):
        attrs = {
                'href': self.path,
                'x': str(self.lastx),
                'y': str(vh - self.scale * self.y - self.render.get_height()),
                'width': str(self.render.get_width()),
                'height': str(self.render.get_height()),
                ns('sizechart', 'origWidth'): str(self.surf.get_width()),
                ns('sizechart', 'origHeight'): str(self.surf.get_height()),
                ns('sizechart', 'scale'): str(self.scale),
                ns('sizechart', 'overlap'): str(self.olap),
                ns('sizechart', 'offsetY'): str(self.y),
                ns('sizechart', 'role'): 'Sprite',
        }
        if self.refy is not None:
            attrs[ns('sizechart', 'referenceY')] = str(self.refy)
        tb.start(ns('svg', 'image'), attrs)
        tb.end(ns('svg', 'image'))

class App:
    def __init__(self, screen):
        self.canvas = Canvas(screen)
        self.sprites = []
        self.selection = None
        self.running = True
        self.keystate = self.ks_default
        self.grid_fore = False
        self.ppu = 128.0
        self.real_units = True
        self.unit = 'm'
        self.buffer = ''
        self.message = ''

    def save_tree(self):
        tb = ET.TreeBuilder()

        r = pygame.Rect(0, 0, 1, 1)
        for spr in self.sprites:
            r.union_ip(spr.rect)
        vh = r.h
        vb = f'0 0 {r.w - r.x} {r.h - r.y}'

        tb.start(ns('svg', 'svg'), {
            ns('svg', 'viewbox'): vb,
            'width': str(r.w - r.x),
            'height': str(r.h - r.y),
            # 'style': 'background-color: #000;',
            ns('sizechart', 'ppu'): str(self.ppu),
            ns('sizechart', 'unit'): self.unit,
            ns('sizechart', 'canvasX'): str(self.canvas.origin[0]),
            ns('sizechart', 'canvasY'): str(self.canvas.origin[1]),
            ns('sizechart', 'canvasScale'): str(self.canvas.scale),
        })

        self.svg_scale(tb, r)

        for spr in self.sprites:
            spr.save(tb, vh)

        tb.end(ns('svg', 'svg'))
        return ET.ElementTree(tb.close())

    def svg_scale(self, tb, r):
        major = set()
        fw = r.w - r.x
        for y in steps(0, r.h / self.ppu):
            major.add(y)
        for y in steps(0, r.h / self.ppu, 1.25):
            sy = r.h - y * self.ppu
            tb.start(ns('svg', 'line'), {
                'x1': '0',
                'x2': str(fw),
                'y1': str(sy),
                'y2': str(sy),
                'stroke': '#077' if abs(y) < 0.001 else '#770',
                'stroke-width': '3' if y in major else '1',
            })
            tb.end(ns('svg', 'line'))
            tb.start(ns('svg', 'text'), {
                'x': '0',
                'y': str(sy),
                'dominant-baseline': 'hanging',
                'fill': '#770',
                'dy': '3',
            })
            tb.data(f'{y}{self.unit}')
            tb.end(ns('svg', 'text'))

    def load_tree(self, root):
        self.ppu = float(root.get(ns('sizechart', 'ppu'), self.ppu))
        self.unit = root.get(ns('sizechart', 'unit'), self.unit)
        self.canvas.origin = (
            float(root.get(ns('sizechart', 'canvasX'), self.canvas.origin[0])),
            float(root.get(ns('sizechart', 'canvasY'), self.canvas.origin[1])),
        )
        self.canvas.scale = float(root.get(
            ns('sizechart', 'canvasScale'),
            self.canvas.scale,
        ))
        del self.sprites[:]
        for child in root:
            if child.get(ns('sizechart', 'role')) == 'Sprite':
                self.sprites.append(Sprite.from_element(child))

    SEL_COLOR = pygame.Color(255, 128, 0, 255)
    def render(self):
        self.canvas.clear()
        self.canvas.blits = 0
        if not self.grid_fore:
            self.render_grid()
        x = 0.0
        for i, spr in enumerate(self.sprites):
            nx = spr.draw(self.canvas, x, self)
            if i == self.selection:
                spr.box(self.canvas, x, self.SEL_COLOR)
            x = nx
        if self.grid_fore:
            self.render_grid()
        self.render_mouse()
        self.render_hud()

    PIX_GRID_COLOR = pygame.Color(255, 255, 255, 32)
    REAL_GRID_COLOR = pygame.Color(255, 255, 0, 32)
    ORIGIN_WIDTH = 3
    def render_grid(self):
        vb = self.canvas.viewbox
        rvb = pygame.Rect(
            *(i / self.ppu for i in (vb.x, vb.y, vb.w, vb.h))
        )
        r = rvb if self.real_units else vb
        col = self.REAL_GRID_COLOR if self.real_units else self.PIX_GRID_COLOR

        for y in steps(r.y, r.h):
            vy = y * self.ppu if self.real_units else y
            w = self.ORIGIN_WIDTH if abs(y) <= 0.001 else 1
            self.canvas.line((vb.x, vy), (vb.x+vb.w, vy), col, w)
            s = self.canvas.text(f'{y:.3f}{self.unit if self.real_units else "px"}', col)
            sx, sy = self.canvas.map_point((vb.x, vy))
            self.canvas.disp.blit(s, (sx, sy+1))

        for x in steps(r.x, r.w):
            vx = x * self.ppu if self.real_units else x
            w = self.ORIGIN_WIDTH if abs(x) <= 0.001 else 1
            self.canvas.line((vx, vb.y), (vx, vb.y+vb.h), col, w)
            s = self.canvas.text(f'{x:.3f}{self.unit if self.real_units else "px"}', col)
            sx, sy = self.canvas.map_point((vx, vb.y))
            sy -= s.get_height()
            sx += 1
            self.canvas.disp.blit(s, (sx, sy))

    def hit_test(self, cpt):
        print(f'hit {cpt}')
        for ix, spr in enumerate(self.sprites):
            if spr.contains(cpt):
                return ix, spr
        return None, None

    MOUSE_COLOR = pygame.Color(0, 255, 255, 255)
    def render_mouse(self):
        mx, my = pygame.mouse.get_pos()
        cx, cy = self.canvas.unmap_point((mx, my))
        pygame.draw.line(
            self.canvas.disp,
            self.MOUSE_COLOR,
            (mx - 5, my),
            (mx + 5, my),
        )
        pygame.draw.line(
            self.canvas.disp,
            self.MOUSE_COLOR,
            (mx, my - 5),
            (mx, my + 5),
        )
        if self.real_units:
            unit = self.unit
            cx, cy = (i / self.ppu for i in (cx, cy))
        else:
            unit = "px"
        s = self.canvas.text(f'{cx:.3f}{unit},{cy:.3f}{unit}', self.MOUSE_COLOR)
        self.canvas.disp.blit(s, (mx, my))

    HUD_COLOR = pygame.Color(0, 0, 255, 255)
    def render_hud(self):
        s = self.canvas.text(self.message, self.HUD_COLOR)
        self.canvas.disp.fill(
            (0, 0, 0, 32),
            (0, 0, self.canvas.disp.get_width(), s.get_height())
        )
        self.canvas.disp.blit(s, (0, 0))

        cp = self.canvas.unmap_point(pygame.mouse.get_pos())
        u = self.unit if self.real_units else "px"
        if self.real_units:
            cp = tuple(i / self.ppu for i in cp)
        cx, cy = cp
        lines = [
            f'Cursor: {cx:.3f}{u},{cy:.3f}{u}',
            f'Blits: {self.canvas.blits}',
        ]
        if self.real_units:
            lines.extend([
                f'Scale: {self.ppu}px/{self.unit}',
            ])
        if self.selection is not None:
            spr = self.sprites[self.selection]
            sw, sh = spr.render.get_size()
            ref = None
            if spr.refy is not None:
                ry = spr.scale * spr.refy
                y = spr.scale * (spr.refy + spr.y)
                dy, dry = y, ry
                u = "px"
                if self.real_units:
                    dy, dry = tuple(i / self.ppu for i in (dy, dry))
                    u = self.unit
                ref = f'{dy:.3f}{u} ({dry:.3f}{u} baseline)'
            lines.extend([
                f'Index: {self.selection}',
                f'Path: {spr.path}',
                f'Scale: {spr.scale:.3f}',
                f'Y-offset: {spr.y:.3f}',
                f'Rendered X: {spr.lastx:.3f}',
                f'Overlap: {spr.olap:.3f}',
                f'Pixel Size: {sw:.3f},{sh:.3f}',
                f'Ref: {ref}',
            ])

        surfs = [self.canvas.text(i, self.HUD_COLOR) for i in lines]
        mw = max(i.get_width() for i in surfs)
        x = self.canvas.disp.get_width() - mw
        y = s.get_height()
        for surf in surfs:
            self.canvas.disp.blit(surf, (x, y))
            y += surf.get_height()

    HANDLED_EVENTS = {
        pygame.KEYDOWN,
        pygame.KEYUP,
        pygame.MOUSEMOTION,
        pygame.MOUSEBUTTONDOWN,
        pygame.MOUSEBUTTONUP,
    }
    def event(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
        elif ev.type in self.HANDLED_EVENTS:
            print(ev)
            self.keystate(ev)

    def sel_offset(self, ds):
        if not self.sprites:
            self.selection = None
        else:
            if self.selection is None:
                self.selection = 0 if ds > 0 else (len(self.sprites) - 1)
            else:
                self.selection = (self.selection + ds) % len(self.sprites)

    def add_to_buffer(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                self.buffer = self.buffer[:-1]
            elif ev.unicode:
                self.buffer += ev.unicode

    def ks_default(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_UP:
                if ev.mod & pygame.KMOD_CTRL:
                    self.canvas.scale *= 2.0
                elif ev.mod & pygame.KMOD_ALT:
                    self.selection = None
                elif ev.mod == pygame.KMOD_NONE:
                    self.canvas.move(dy=0.1 * self.canvas.viewbox.h)
            elif ev.key == pygame.K_DOWN:
                if ev.mod & pygame.KMOD_CTRL:
                    self.canvas.scale /= 2.0
                elif ev.mod == pygame.KMOD_NONE:
                    self.canvas.move(dy=-0.1 * self.canvas.viewbox.h)
            elif ev.key == pygame.K_LEFT:
                if ev.mod == pygame.KMOD_NONE:
                    self.canvas.move(dx=-0.1 * self.canvas.viewbox.w)
                elif ev.mod & pygame.KMOD_ALT:
                    self.sel_offset(-1)
                elif ev.mod & pygame.KMOD_CTRL:
                    if self.selection is not None and self.selection > 0:
                        self.sprites[self.selection], self.sprites[self.selection - 1] = \
                            self.sprites[self.selection - 1], self.sprites[self.selection]
                        self.selection -= 1
            elif ev.key == pygame.K_RIGHT:
                if ev.mod == pygame.KMOD_NONE:
                    self.canvas.move(dx=0.1 * self.canvas.viewbox.w)
                elif ev.mod & pygame.KMOD_ALT:
                    self.sel_offset(1)
                elif ev.mod & pygame.KMOD_CTRL:
                    if self.selection is not None and self.selection < len(self.sprites) - 1:
                        self.sprites[self.selection], self.sprites[self.selection + 1] = \
                            self.sprites[self.selection + 1], self.sprites[self.selection]
                        self.selection += 1
            elif ev.key == pygame.K_g:
                self.grid_fore = True
            elif ev.key == pygame.K_r:
                self.real_units = not self.real_units
            elif ev.key == pygame.K_z and self.selection is not None:
                self.keystate = self.ks_reference
            elif ev.key == pygame.K_t and self.selection is not None:
                self.origy = self.sprites[self.selection].y
                self.origmy = pygame.mouse.get_pos()[1]
                self.keystate = self.ks_move
            elif ev.key == pygame.K_s and self.selection is not None:
                self.origmy = pygame.mouse.get_pos()[1]
                self.keystate = self.ks_scale
            elif ev.key == pygame.K_o and self.selection is not None:
                if self.selection > 0:
                    self.origmx = pygame.mouse.get_pos()[0]
                    self.keystate = self.ks_offset
                else:
                    self.message = "Can't offset the first sprite"
            elif ev.key == pygame.K_l:
                self.buffer = ''
                self.message = f'Load: {CURSOR}'
                self.keystate = self.ks_load
            elif ev.key == pygame.K_d and self.selection is not None:
                self.message = 'Really delete? (y/n)'
                self.keystate = self.ks_delete
            elif ev.key == pygame.K_w:
                self.buffer = 'chart.svg'
                self.message = f'Write: {self.buffer}{CURSOR}'
                self.keystate = self.ks_write
        elif ev.type == pygame.KEYUP:
            if ev.key == pygame.K_g:
                self.grid_fore = False
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == 1:
                self.drag_pos = ev.pos
                self.drag_origin = self.canvas.origin
                self.keystate = self.ks_dragging
            elif ev.button == 4:
                pt = self.canvas.unmap_point(ev.pos)
                self.canvas.scale_into(1.1, pt)
            elif ev.button == 5:
                pt = self.canvas.unmap_point(ev.pos)
                self.canvas.scale_into(1/1.1, pt)

    def ks_dragging(self, ev):
        if ev.type == pygame.MOUSEBUTTONUP:
            if ev.pos == self.drag_pos:
                ix, _ = self.hit_test(self.canvas.unmap_point(ev.pos))
                self.selection = ix
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            x, y = tuple(n - o for n, o in zip(ev.pos, self.drag_pos))
            delta = self.canvas.unmap_scaled((-x, y))
            self.canvas.origin = tuple(
                o + d for o, d in zip(self.drag_origin, delta)
            )

    def ks_reference(self, ev):
        spr = self.sprites[self.selection]
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == 3:
                spr.refy = None
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            _, y = self.canvas.unmap_point(ev.pos)
            spr.refy = (y - spr.y) / spr.scale
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_0:
                spr.y = -spr.refy
                spr.refy = None
                self.keystate = self.ks_default

    def ks_move(self, ev):
        spr = self.sprites[self.selection]
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            _, dy = self.canvas.unmap_scaled((0, self.origmy - ev.pos[1]))
            spr.y = self.origy + dy

    def ks_scale(self, ev):
        spr = self.sprites[self.selection]
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            d = self.origmy - ev.pos[1]
            self.origmy = ev.pos[1]
            base = 1.01
            mods = pygame.key.get_mods()
            if mods & pygame.KMOD_CTRL:
                base = 1.001
            elif mods & pygame.KMOD_SHIFT:
                base = 1.1
            spr.scale *= base**d
            print(f'new scale: {spr.scale}')

    def ks_offset(self, ev):
        spr = self.sprites[self.selection - 1]
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            dx = ev.pos[0] - self.origmx
            self.origmx = ev.pos[0]
            spr.olap += dx * 0.01

    def ks_load(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_RETURN:
                try:
                    spr = Sprite(
                        pygame.image.load(self.buffer),
                        self.buffer,
                    )
                except FileNotFoundError as e:
                    traceback.print_exc()
                    self.message = repr(e)
                else:
                    if self.selection is not None:
                        self.sprites.insert(self.selection, spr)
                    else:
                        self.sprites.append(spr)
                self.keystate = self.ks_default
                self.message = ''
                return
            elif ev.key == pygame.K_TAB:
                opts = glob.glob(self.buffer + '*')
                if opts:
                    pfx = os.path.commonprefix(opts)
                    if len(pfx) > len(self.buffer):
                        self.buffer = pfx
            else:
                self.add_to_buffer(ev)
            self.message = f'Load: {self.buffer}{CURSOR}'

    def ks_delete(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_y:
                del self.sprites[self.selection]
                self.selection = None
            self.keystate = self.ks_default
            self.message = ''

    def ks_write(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_RETURN:
                et = self.save_tree()
                et.write(self.buffer, 'unicode')
                self.keystate = self.ks_default
                self.message = ''
                return
            elif ev.key == pygame.K_TAB:
                opts = glob.glob(self.buffer + '*')
                if opts:
                    pfx = os.path.commonprefix(opts)
                    if len(pfx) > len(self.buffer):
                        self.buffer = pfx
            else:
                self.add_to_buffer(ev)
            self.message = f'Write: {self.buffer}{CURSOR}'

def main():
    import sys
    pygame.init()
    pygame.display.set_caption('sizechart')
    app = App(pygame.display.set_mode(
        (800, 600),
        pygame.RESIZABLE
    ))
    if len(sys.argv) > 1:
        et = ET.ElementTree(file=sys.argv[1])
        app.load_tree(et.getroot())
    clock = pygame.time.Clock()
    # begin test code
    #path = "images/Grissess_Full_transparent.png"
    #gris = pygame.image.load(path)
    #for i in range(3):
    #    app.sprites.append(Sprite(gris, path))
    #app.selection = 1

    while app.running:
        for ev in pygame.event.get():
            app.event(ev)
        app.render()
        pygame.display.flip()
        clock.tick(60)

if __name__ == '__main__':
    main()
