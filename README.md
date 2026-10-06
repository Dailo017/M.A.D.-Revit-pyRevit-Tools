# M.A.D – Revit pyRevit Tools

A [pyRevit](https://github.com/pyrevitlabs/pyRevit) extension that adds a **M.A.D tools** tab to the Revit ribbon with tools for general modelling, MEP and structure.

---

## Installation

### Option 1 – pyRevit CLI (recommended)

```bash
pyrevit extend ui MAD https://github.com/Dailo017/M.A.D-Revit-pyRevit-Tools.git
```

Then click **pyRevit ▸ Reload** (or restart Revit).

### Option 2 – Manual

1. Clone or download this repository into a folder named **`MAD.extension`**
   (the `.extension` suffix is required for pyRevit to recognize it).
2. In Revit, go to **pyRevit ▸ Settings ▸ Custom Extension Directories** and add the
   **parent** folder of `MAD.extension`.
3. Click **Save Settings and Reload**.

### Requirements

- Autodesk Revit
- [pyRevit](https://github.com/pyrevitlabs/pyRevit/releases) (includes IronPython and `rpw`, used by some tools)

---

## Tools

### GEN – General

| Tool | Description |
|------|-------------|
| **Room Tags From Link** | Places a room tag on every room of a linked model, in every floor plan view of the project. |
| **UPPER / Lowercase** | Renames the families and/or types of the project to UPPERCASE or lowercase. |

### MEP

| Tool | Description |
|------|-------------|
| **Clear Height MEP** | Calculates the free space between pipes, ducts and cable trays and the floor below them (floors of a linked model). A ray is cast down from the start, middle and end of each element; the shortest distance is stored in the chosen parameter. |
| **Copy Room Name** | Copies the name of the room (from a linked model) containing each plumbing fixture, plumbing equipment and pipe accessory into the chosen parameter. Uses a 15 cm tolerance to the room boundary; otherwise writes `Outside Room`. |
| **Host Parameter** | Copies a parameter value from each duct / pipe to its insulation and lining (same parameter name on both). |
| **MEP Network** | Creates a network of ducts or pipes from detail/model lines: places placeholders, connects them at shared points (elbow, tee, cross) and converts them into real ducts / pipes. |
| **Pipe Orientation** | Classifies each pipe as vertical, horizontal or sloped and writes the result in the chosen parameter. |
| **Reference Level** | Changes the reference level of the selected MEP elements **without moving them** (the offset is recalculated). |
| **TagHVAC** | Tags every vertical pipe and duct in the active 2D view (10° tolerance), grouped by system type, with a tag type chosen per system in a scrollable, resizable form. Already-tagged elements can be skipped. Tags are offset 100 cm with a leader; overlapping tag heads are pushed apart automatically (without rotating them). All tags are created in a single transaction (one Undo). |
| **TagPLBG** | Same detection, form and single transaction as TagHVAC, but tags are placed centered on the element's midpoint, without a leader and without overlap resolution. |

### STR – Structure

| Tool | Description |
|------|-------------|
| **Attach Walls** | Allows the join at both ends of the selected walls. |
| **Detach Walls** | Disallows the join at both ends of the selected walls. |
| **Clear Height** | Calculates the free space between each beam and the floor below it and writes it in the chosen parameter. |
| **RSV NGF** | Calculates the NGF elevation of the bottom of the selected reservations: `level elevation + offset − (RSV_H or RSV_D) / 2`. |
| **Select Thick Walls** | Selects every wall in the project thicker than 35 cm. |
| **Split Walls** | Splits each selected wall into one wall per layer of its compound structure, creating a wall type per layer named `<Material> (<width>cm)`. |
| **Sync Doors Windows** | Synchronizes the doors and windows of a linked ARC model into the active STR model: maps each ARC family to an STR family, creates missing types, hosts them in the nearest wall, and updates/deletes previously synced elements (tracked by UniqueId in *Comments*). |
| **Walls From Lines** | Creates walls from pairs of parallel model lines (e.g. both faces of a wall in a CAD plan): finds the pairs, draws a center line and creates a wall of the chosen type on it. |

> Each button's tooltip in Revit shows the full description, how-to steps and changelog.

### Parameters

Several tools write their result into a parameter you type in a form
(Clear Height, Clear Height MEP, Copy Room Name, Pipe Orientation, RSV NGF).
That parameter must already exist as an **instance project parameter** of the right type
(text or length) on the target categories — the tool will warn you if it doesn't.

---

## Repository structure

```
MAD.extension/
├── README.md
├── LICENSE
└── M.A.D tools.tab/
    ├── GEN.panel/
    ├── MEP.panel/
    └── STR.panel/
        └── <Tool>.pushbutton/
            ├── script.py
            └── icon.png
```

---

## Credits

- **Dailo Lorenzo Perez** – author of most tools.
- **Split Walls** – adapted from Mohamed Mostafa Bedair, Joven Mark Gumana and Erik Frits.
- **Walls From Lines** – adapted from Aaron Rumple.

## License

[MIT](LICENSE) © 2026 Dailo017
