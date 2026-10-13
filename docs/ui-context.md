### UI Context

#### Theme
The visual language for the Google Gemini Notebook MCP bridge (encompassing the Manifest V3 extension popup, options page, and local pairing CLI) follows a **dark technical workspace** aesthetic. It prioritizes high legibility, information density, and unambiguous security state visualization. The interface utilizes deep slate and near-black surfaces, subtle borders, crisp monospace typography for protocol identifiers, and distinct semantic accent colors to represent cryptographic connection health.

#### Colors
All interface components, extension popups, and webviews must strictly utilize the following CSS custom property tokens—no hardcoded hex values are permitted:

| Role | CSS Variable | Value | Usage |
| :--- | :--- | :--- | :--- |
| **Page Background** | `--bg-base` | `#0B0F19` | Main application and popup background |
| **Surface** | `--bg-surface` | `#111827` | Cards, panels, and input containers |
| **Elevated Surface** | `--bg-elevated` | `#1F2937` | Modals, dropdown menus, and hover states |
| **Primary Text** | `--text-primary` | `#F9FAFB` | Main headings, notebook titles, and body copy |
| **Muted Text** | `--text-muted` | `#9CA3AF` | Secondary labels, timestamps, and UUID subtext |
| **Primary Accent** | `--accent-primary` | `#3B82F6` | Primary action buttons and focus rings |
| **Accent Hover** | `--accent-hover` | `#2563EB` | Button hover and active press states |
| **Border Default** | `--border-default` | `#374151` | Subtle container separators and input borders |
| **Border Focus** | `--border-focus` | `#60A5FA` | Active keyboard focus indicators |
| **State Success** | `--state-success` | `#10B981` | Connected status, DBSC verified, ready |
| **State Warning** | `--state-warning` | `#F59E0B` | Ingestion syncing, processing, rate cooldown |
| **State Error** | `--state-error` | `#EF4444` | Disconnected, auth required, upstream drift |

#### Typography
| Role | Font Family | Variable | Usage |
| :--- | :--- | :--- | :--- |
| **UI Text** | Inter, Geist Sans, system-ui | `--font-sans` | Extension labels, buttons, navigation, status text |
| **Code / Data** | JetBrains Mono, Geist Mono, monospace | `--font-mono` | Notebook IDs, RPC method tags, JSON payloads, stream logs |

#### Border Radius Scale
| Context | Class | Radius Value |
| :--- | :--- | :--- |
| **Inline / Tags** | `rounded-md` | `6px` (Badges, source type chips, status pills) |
| **Inputs / Buttons**| `rounded-lg` | `8px` (Form controls, action buttons, list rows) |
| **Cards / Panels** | `rounded-xl` | `12px` (Extension popup container, modal dialogs) |

#### Component Library & Styling Principles
* **Extension UI**: Lightweight pre-compiled HTML/CSS with Tailwind CSS utility classes. Zero heavy runtime frameworks (React/Vue) in the extension popup to minimize memory footprint and eliminate V8 cold-start latency.
* **Component Inventory**:
  * `ConnectionHealthBadge`: Displays live IPC status (`Connected`, `Reconnecting`, `Disconnected`).
  * `AccountSelector`: Displays authenticated Google profile (`oM1Kwf`) and active `authuser` index.
  * `NotebookAllowlistCard`: Interactive checklist allowing users to approve/revoke specific notebooks into `allowlist.json`.
  * `SourceReadinessIndicator`: Animated pill displaying indexing status (`PREPARING`, `PROCESSING`, `READY`, `FAILED`).
  * `SecurityAuditDrawer`: Collapsible view confirming zero cookies exported and active DBSC TPM status.

#### Layout Patterns
* **Extension Popup (360px × 480px)**:
  * Top Bar: Logo, Connection Status Indicator, and Active Google Account badge.
  * Main Viewport: Scrollable list of allowlisted notebooks with source counts and sync states.
  * Action Bar: "Connect this Browser" toggle and link to local CLI documentation.
* **CLI Pairing Dashboard (Terminal ANSI / Rich UI)**:
  * Two-column split: Left pane displays Broker daemon uptime, IPC socket health, and memory usage; Right pane streams real-time mutation journal events (`prepared` -> `sent` -> `confirmed`).

#### Icons
* **Icon Set**: Lucide Icons (stroke width: `1.75px`).
* **Semantic Icon Bindings**:
  * `ShieldCheck` (Emerald): Hardware DBSC TPM signature verified.
  * `Radio` (Blue): Native Messaging IPC connection active.
  * `BookOpen` (Text Primary): Notebook resource.
  * `FileText` (Text Muted): Document source.
  * `Link2` (Text Muted): URL source.
  * `RefreshCw` (Amber, spinning): Source indexing in progress.
  * `AlertCircle` (Crimson): Human authentication action required.
