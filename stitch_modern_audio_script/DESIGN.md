---
name: Architectural Precision
colors:
  surface: '#0b1326'
  surface-dim: '#0b1326'
  surface-bright: '#31394d'
  surface-container-lowest: '#060e20'
  surface-container-low: '#131b2e'
  surface-container: '#171f33'
  surface-container-high: '#222a3d'
  surface-container-highest: '#2d3449'
  on-surface: '#dae2fd'
  on-surface-variant: '#e6beb2'
  inverse-surface: '#dae2fd'
  inverse-on-surface: '#283044'
  outline: '#ac897e'
  outline-variant: '#5c4037'
  surface-tint: '#ffb59e'
  primary: '#ffb59e'
  on-primary: '#5e1700'
  primary-container: '#ff5717'
  on-primary-container: '#521300'
  inverse-primary: '#ad3300'
  secondary: '#46eaed'
  on-secondary: '#003738'
  secondary-container: '#00cdd0'
  on-secondary-container: '#005253'
  tertiary: '#a4c9ff'
  on-tertiary: '#00315d'
  tertiary-container: '#1c92ff'
  on-tertiary-container: '#002a52'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdbd0'
  primary-fixed-dim: '#ffb59e'
  on-primary-fixed: '#3a0b00'
  on-primary-fixed-variant: '#842500'
  secondary-fixed: '#5af8fb'
  secondary-fixed-dim: '#2ddbde'
  on-secondary-fixed: '#002020'
  on-secondary-fixed-variant: '#004f51'
  tertiary-fixed: '#d4e3ff'
  tertiary-fixed-dim: '#a4c9ff'
  on-tertiary-fixed: '#001c39'
  on-tertiary-fixed-variant: '#004884'
  background: '#0b1326'
  on-background: '#dae2fd'
  surface-variant: '#2d3449'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
  mono-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 28px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 12px
  margin-mobile: 16px
---

## Brand & Style

This design system is built for the power user who demands clarity, speed, and technical rigor. It moves away from the ethereal, glowing aesthetics of consumer AI, opting instead for a **Modern Pro-Tool** aesthetic. 

The style is characterized by high-contrast functionalism, drawing inspiration from high-end industrial hardware and developer environments. It prioritizes information density and structural hierarchy, ensuring that complex controls—like model parameters and transcription logs—remain legible and accessible. The emotional tone is authoritative, precise, and utilitarian, framing the tool as an extension of the user’s professional workflow rather than a decorative gadget.

## Colors

The palette is anchored by a deep slate foundation to reduce eye strain during long sessions.
- **Primary (International Orange):** Reserved strictly for critical actions like "Record" or "Save." It signals high-priority interaction.
- **Secondary (Electric Teal):** Used for state indications, active toggles, and data highlights to provide a cool contrast to the primary action color.
- **Neutrals:** A range of slates (`#020617` to `#334155`) creates depth without relying on pure blacks, maintaining a sophisticated "engineered" feel.
- **Semantic Colors:** Success (Green), Warning (Amber), and Error (Crimson) follow the same high-chroma, architectural logic to ensure clarity against the dark backdrop.

## Typography

Typography is treated as a structural element. **Inter** provides a clean, neutral sans-serif foundation for most interface elements, ensuring high legibility at small sizes. 

**JetBrains Mono** is utilized for transcription logs, technical metadata, and status reports to emphasize the "under-the-hood" nature of the tool. 

Hierarchy is established through weight and uppercase labels rather than extreme size shifts. On mobile, headlines are tightened to preserve vertical space, ensuring the transcription area remains the focal point.

## Layout & Spacing

The layout follows a strict **8px grid system**. 

### Mobile Architecture
- **Header:** Houses the title and global status.
- **Primary Controls:** Language and Profile selectors are stacked at the top using a 2-column grid for compactness.
- **The "Engine" Room:** Prompt editors and secondary settings are placed in collapsible or clearly bordered sections.
- **Transcription Area:** Fixed minimum height of 40% of the viewport to ensure the main output is always visible while scrolling through logs.
- **Action Bar:** The "Record" button is pinned or highly prominent at the bottom of the control stack for easy thumb access.

## Elevation & Depth

Hierarchy is achieved through **Tonal Layering** rather than traditional drop shadows.
- **Level 0 (Background):** Deepest slate (`#020617`).
- **Level 1 (Sections):** A lighter slate (`#0F172A`) with a subtle 1px border (`#1E293B`) to define the boundaries of different functional areas (e.g., Prompt Editor vs. History).
- **Level 2 (Inputs/Buttons):** These sit "on top" of sections, using slight value shifts and crisp, 1px inset borders to create a tactile, "machined" look.
- **Shadows:** When used for menus or overlays, shadows are ultra-tight and low-opacity (20% alpha) to maintain the flat, pro-tool aesthetic.

## Shapes

The design uses a **Soft (0.25rem)** roundedness level to balance technical precision with modern UI expectations. 
- Elements like dropdowns, input fields, and small chips use a 4px radius.
- Larger containers like the Transcription box or Logs panel use 8px (`rounded-lg`).
- Buttons remain slightly more "blocked" to feel sturdy and intentional.
- Toggles and switches are the only elements allowed to be fully circular to distinguish them as binary state controls.

## Components

### Buttons
- **Primary Action (Record):** International Orange background, white text, bold weight. Minimal hover shift to a deeper orange.
- **Secondary Action (Copy/Clear):** Slate background with a high-contrast border. 
- **Ghost Buttons:** For less frequent actions like "Guardar Prompt," using only text and an underline or subtle border on hover.

### Input Fields & Dropdowns
- High-contrast labels in `label-caps` style above the field.
- Background is darker than the surrounding container to create an "etched" effect.
- Active states use a thin Electric Teal border.

### Chips & Badges
- Used for model status (e.g., "base", "small"). These are rectangular with minimal rounding and monospaced text to emphasize technical specs.

### Transcription Area
- Large, high-contrast text area. Use a subtle vertical gradient at the top and bottom to indicate "more content" when text overflows.

### Logs
- Continuous stream of `mono-sm` text. Dimmed colors for timestamps and metadata, with Electric Teal used for successful events.