# sizechart

It's software that makes size charts.

## Installation

Make sure you have a working `pyglet` and `pygame` (the latter out of
laziness). I'm still terrible at packaging Python, but check your distribution
package manager (or the projects' home pages), and/or use `pip` or
`easy_install`.

Use a Python greater than 3.6. I believe it's tested on Py3.10, if not Py3.11,
as of this writing.

## Running

```
python sizechart.py
```

Or, to load an existing file called `file.svg`:

```
python sizechart.py file.svg
```

## Documentation

This is hardly replete, but it's enough to get started.

This program is a _modal_ editor (like `vim`); most keyboard keys do their work
_without_ any modifiers held. That "work" still often involves multiple
keystrokes (or input events in general), which probably takes you through
multiple "input modes", like "in the middle of translating" or "putting a
reference line down". The starting mode is "default" (`ks_default`). From there
you can:

- **Navigation**
  - Use the arrow keys _without modifiers_ to move around;
    - Ctrl+ (or Cmd+) up/down will zoom in and out;
  - Enter `dragging` by left-clicking;
  - Scroll to zoom in and zoom out;
- **Visual Utilities**
  - Press and hold `g` to see the grid in the foreground;
  - Tap `r` to toggle between pixels and "real units" according to your scale;
- **Loading and Saving**
  - Tap `l` to load a new Image;
  - Tap `w` to enter `write` mode (for saving the chart--do this often!);
- **Selecting Things** (but see also `dragging`, below)
  - Alt+Up clears the selection;
  - Alt+Left and +Right moves the "primary" (last) selection to the next Image to the left or right;
    - If nothing is selected, going "next" selects the first, and "previous" selects the last Image, respectively.
  - Ctrl+`a` selects every Image;
  - Ctrl+`A` (Ctrl+Shift+`a`) unselects everything;
- **Operations on Anything** (both Images and Viewports)
  - Tap `n` to enter `name` mode (and rename it);
    - The Viewport name is the filename that results; it needs to have an extension. The Image name, aside from rendering at the bottom, will be the base filename (plus `.asset`) if it's turned into an asset with `A` (Shift+`a`).
  - Tap `d` to enter `delete` mode (confirming if you _really_ want to delete it);
- **The Clipboard**
  - Tap `y` ("yank") to copy selected objects (Images, Viewports) into your clipboard;
  - Tap `p` to paste the selection from the clipboard;
    - There are some big caveats here. First, copy/paste uses the save/load machinery, so it can transfer anything that can be saved to or loaded from the chart. However, unless you specified otherwise, image paths are relative, which means the chart to which you paste _must_ be in the same directory/folder from the one which you copy for this to work smoothly. This is true even for assets. This limitation may be lifted in the future, but with its own troubles--e.g., storing absolute paths will make the charts non-portable if the containing directory is moved.
- **Operations on Images**
  - Tap `o` to enter `offset` mode;
  - Tap `s` to enter `scale` mode;
  - Tap `t` to enter `move` mode;
  - Tap `z` to enter `reference` mode;
  - Ctrl+Left and +Right moves _all_ selected images left or right in the order;
  - Tap `A` (Shift+`a`) to turn _all_ selected images into "assets";
    - These assets will be written as `NAME.asset` for their given `NAME` into the same directory from which their image was loaded.
- **Operations on Viewports** (generally, if you have mixed Images and Viewports in the selection, the Images win key conflicts)
  - Tap `k` to render selected Viewports (or all viewports if none are selected);
  - Tap `s` to enter `vp_scale` (change the pixel/unit scale relative to the whole chart);
  - Tap `t` to enter `vp_origin` (change the bottom-left corner);
  - Tap `z` to enter `vp_opposite` (change the top-right corner);
- Tap `v` to enter `viewport` mode (_creating_ a Viewport).

The modes `offset`, `scale`, `move`, `reference`, `vp_origin`, and
`vp_opposite` mostly just rubber-band something to your mouse cursor:

- `offset` lets you slide the selected image back and forth relative to the previous image (you can't do this with the first image);
- `scale` lets you scale up and down the image;
  - Hold `Shift` for coarse, and `Ctrl` for fine, adjustments;
- `move` lets you slide an image up and down;
- `reference` lets you draw the "reference line", a horizontal line on an image you can use as the measuring point;
  - If you tap `0` while in this mode, the image slides down so that the line is flush with the floor (0 units height), and you get kicked back to `default` mode.
- `vp_origin` and `vp_opposite` move the lower left and upper right corner, respectively, of selected Viewports to wherever the mouse cursor is.

In general, left-click accepts a change, while right-click reverts the change.
Pressing `0` in `reference` mode also technically cancels the change, clearing
the reference height.

`dragging` is a little special: if you click and drag, most of the time you
drag the view around. However, if you don't move the mouse (just click), you
select the closest thing under your cursor. This is the only way to select
Viewports for now.

In `load`, `write`, and `name` modes, you can type something at a prompt that
appears in the top-left corner--the name of the image file to load, the chart
file to save, or the name of the selected image, respectively. Press `Enter` to
stop entering text. Backspace works as expected, but don't expect much else. In
`load` mode, you get Tab-completion, so you can tap Tab to complete the next
unambiguous part (shared by all possible files/dirs). `write` mode
automatically uses the last name this chart was loaded/saved as, so you usually
just tap `w` then `Enter` to save changes.

`delete` mode asks you if "you're sure"; tapping `y` confirms the delete.
Anything other key cancels.

`viewport` mode creates a viewport in two steps: first, click the origin
(bottom left), then the opposite (top right); once you do, you drop into `name`
mode setting the name (which is the filename) of your fresh new viewport. It's
also selected, so--after you're done with that--you can, e.g., scale it or
adjust it.

### Assets

Most of the time, you `l`oad an image, and all is well. However, if you
maintain multiple charts, it can be burdensome and error-prone to maintain
redundant information for the same images. If you find yourself needing to copy
images in particular, consider using an "asset" instead; this is a small file
that indirects to the "real" image file, but also contains all of the other
Image data, such as scale, offset, and reference height. Changes to assets get
saved with the chart, so if you tweak an Image's height, and that Image was
loaded from an Asset, the underlying Asset will have a different height, even
on the other charts in which it's placed.

### Chart Data File Format

The rendered chart is a standards-conforming `SVG` image; you can save it with
a `.svg` extension and, say, open it in a browser or Inkscape and expect it to
work. Although the Viewports change this interpretation arbitrarily, the "units
per pixel" refers to SVG pixels as seen in conforming viewers. The extra data
in the chart is saved in XML-namespaced attributes to avoid interfering with
the SVG function.

This means you can use an SVG editor to edit charts, with care. Most
transform-based properties, such as the actual rendered position and scale,
will be ignored on load unless you also change the sizechart-specific
properties such as `offsetY` and `scale`. You can also get an XML editor and
change certain properties, for example to enter Unicode in the `name` field of
any object, or change the `averageColor` used to draw the name of Images. For
some properties, like `ppu` (pixels per unit) and `unit` (the actual suffix
unit string), this is the only way to change these values. The
sufficiently-motivated could use a text editor in place of an XML editor for
small changes.

## License

GPL-3.0, see `COPYING` for details.
