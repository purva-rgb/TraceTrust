'use client'

import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  Box,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  ClipboardCheck,
  Factory,
  FileSearch,
  History,
  LayoutDashboard,
  MapPin,
  Menu,
  PackageCheck,
  Plus,
  QrCode,
  Search,
  Settings,
  ShieldCheck,
  Truck,
  UserRound,
  X,
} from 'lucide-react'

type PageKey = 'Overview' | 'Products' | 'QR Verification' | 'Supply Chain' | 'Alerts' | 'Event History' | 'Settings'

type Product = {
  id: string
  name: string
  batch: string
  manufacturer: string
  custodian: string
  status: 'Verified' | 'In transit' | 'Review'
  updated: string
}

const navItems: { label: PageKey; icon: typeof LayoutDashboard }[] = [
  { label: 'Overview', icon: LayoutDashboard },
  { label: 'Products', icon: Box },
  { label: 'QR Verification', icon: QrCode },
  { label: 'Supply Chain', icon: Truck },
  { label: 'Alerts', icon: Bell },
  { label: 'Event History', icon: History },
  { label: 'Settings', icon: Settings },
]

const productImages: Record<string, string> = {
  'TT-AX4-9021': 'https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?auto=format&fit=crop&w=160&q=80',
  'TT-NV2-1184': 'https://images.unsplash.com/photo-1607619056574-7b8d3ee536b2?auto=format&fit=crop&w=160&q=80',
  'TT-OR7-4402': 'https://images.unsplash.com/photo-1611930022073-b7a4ba5fcccd?auto=format&fit=crop&w=160&q=80',
  'TT-CL8-7210': 'https://images.unsplash.com/photo-1556228578-8c89e7adf883?auto=format&fit=crop&w=160&q=80',
  'TT-VA1-3349': 'https://images.unsplash.com/photo-1585435557343-3b092031a831?auto=format&fit=crop&w=160&q=80',
}
const logisticsImage = 'https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?auto=format&fit=crop&w=1200&q=82'
const scanImage = 'https://images.unsplash.com/photo-1587143910090-3d2d2e8d7a8e?auto=format&fit=crop&w=500&q=80'

const initialProducts: Product[] = [
  { id: 'TT-AX4-9021', name: 'Asteria Serum 30ml', batch: 'AS-2408-B', manufacturer: 'Asteria Labs', custodian: 'Northline Retail', status: 'Verified', updated: 'Today, 09:42' },
  { id: 'TT-NV2-1184', name: 'Novera Vitamin D3', batch: 'NV-2407-A', manufacturer: 'Novera Health', custodian: 'Deltaway Distribution', status: 'In transit', updated: 'Yesterday, 16:18' },
  { id: 'TT-OR7-4402', name: 'Orison Sleep Complex', batch: 'OR-2406-C', manufacturer: 'Orison Wellness', custodian: 'Orison Wellness', status: 'Review', updated: 'Jun 18, 11:05' },
  { id: 'TT-CL8-7210', name: 'Clarity SPF 50', batch: 'CL-2408-A', manufacturer: 'Clarity Labs', custodian: 'Northline Retail', status: 'Verified', updated: 'Jun 17, 14:33' },
  { id: 'TT-VA1-3349', name: 'Vantage Magnesium', batch: 'VA-2405-D', manufacturer: 'Vantage Nutrition', custodian: 'Harborpoint Warehouse', status: 'Verified', updated: 'Jun 16, 08:27' },
]

const events = [
  { time: '09:42', title: 'Custody received', detail: 'Asteria Serum 30ml · Northline Retail', state: 'verified' },
  { time: '08:16', title: 'Shipment departed', detail: 'Novera Vitamin D3 · Deltaway Distribution', state: 'neutral' },
  { time: 'Yesterday', title: 'QR scan pattern flagged', detail: 'Orison Sleep Complex · 3 locations in 42 min', state: 'warning' },
  { time: 'Jun 18', title: 'Batch record updated', detail: 'Clarity SPF 50 · Clarity Labs', state: 'verified' },
]

function StatusBadge({ status }: { status: Product['status'] }) {
  return <span className={`status-badge ${status.toLowerCase().replace(' ', '-')}`}><span className="status-dot" />{status}</span>
}

function ProductThumb({ product, large = false }: { product: Product; large?: boolean }) {
  return <div className={`product-thumb ${large ? 'large' : ''}`}><img src={productImages[product.id]} alt={`${product.name} packaging`} onError={(event) => { event.currentTarget.style.display = 'none' }} /><span>{product.name.split(' ').map((word) => word[0]).join('').slice(0, 2)}</span></div>
}

function Sidebar({ active, onNavigate }: { active: PageKey; onNavigate: (page: PageKey) => void }) {
  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark"><ShieldCheck /></div><div><strong>TraceTrust</strong><span>Track the Journey. Trust the Trace.</span></div></div>
    <div className="workspace-label">OPERATIONS</div>
    <nav aria-label="Primary navigation">
      {navItems.map(({ label, icon: Icon }) => <button key={label} className={`nav-item ${active === label ? 'active' : ''}`} onClick={() => onNavigate(label)}><Icon /><span>{label}</span>{label === 'Alerts' && <span className="nav-count">3</span>}</button>)}
    </nav>
    <div className="sidebar-footer"><div className="environment"><span className="live-dot" />Demo environment</div><div className="user-block"><div className="avatar">AM</div><div><strong>Alex Morgan</strong><span>Operations lead</span></div><ChevronRight /></div></div>
  </aside>
}

function Topbar({ active, onMenu }: { active: PageKey; onMenu: () => void }) {
  return <header className="topbar"><button className="mobile-menu" onClick={onMenu} aria-label="Open navigation"><Menu /></button><div className="breadcrumbs"><span>Workspace</span><ChevronRight /><strong>{active}</strong></div><div className="top-actions"><span className="simulated-label"><span className="live-dot" />Simulated data</span><button className="icon-button" aria-label="Help"><CircleHelp /></button><div className="top-avatar">AM</div></div></header>
}

function Metric({ label, value, note, tone }: { label: string; value: string; note: string; tone: string }) {
  return <div className="metric"><div className={`metric-icon ${tone}`}><PackageCheck /></div><div><span className="metric-label">{label}</span><strong>{value}</strong><span className="metric-note">{note}</span></div></div>
}

function Overview({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  return <>
    <PageHeader eyebrow="OPERATIONS OVERVIEW" title="Supply Chain Overview" description="Monitor product movement, verify authorized records, and investigate suspicious activity." />
    <div className="overview-intro"><div><span className="eyebrow">CONNECTED OPERATIONS</span><h2>Every handoff, accounted for.</h2><p>TraceTrust gives your team a clear view from warehouse intake to the final shelf, with a trusted record behind every movement.</p></div><img src={logisticsImage} alt="Warehouse team preparing labeled shipping packages" onError={(event) => { event.currentTarget.style.display = 'none' }} /></div>
    <div className="metric-grid"><Metric label="Registered products" value="2,481" note="Across 18 active batches" tone="sage" /><Metric label="Active shipments" value="186" note="12 arriving today" tone="blue" /><Metric label="Verified records" value="98.4%" note="Last 30 days" tone="sage" /><Metric label="Suspicious alerts" value="3" note="2 need review" tone="warning" /></div>
    <div className="overview-grid">
      <section className="surface event-surface"><SectionHeading title="Recent events" action="View event history" onAction={() => onNavigate('Event History')} /><div className="event-list">{events.map((event) => <div className="event-row" key={event.time + event.title}><div className={`event-indicator ${event.state}`} /> <div className="event-copy"><strong>{event.title}</strong><span>{event.detail}</span></div><time>{event.time}</time></div>)}</div></section>
      <section className="surface journey-surface"><SectionHeading title="Shipment journey" action="View shipments" onAction={() => onNavigate('Supply Chain')} /><p className="surface-subtitle">TT-NV2-1184 · Novera Vitamin D3</p><div className="journey"><JourneyStep icon={Factory} label="Manufacturer" name="Novera Health" done /><JourneyStep icon={Box} label="Warehouse" name="Harborpoint" done /><JourneyStep icon={Truck} label="Distributor" name="Deltaway" current /><JourneyStep icon={MapPin} label="Retailer" name="Northline" /></div><div className="journey-footer"><span>Expected arrival</span><strong>Jun 21, 2024</strong></div></section>
      <section className="surface quick-surface"><SectionHeading title="Quick actions" /><div className="quick-actions"><button onClick={() => onNavigate('Products')}><Plus /><span><strong>Register product</strong><small>Add a new product record</small></span><ArrowRight /></button><button onClick={() => onNavigate('QR Verification')}><QrCode /><span><strong>Verify a product</strong><small>Check an ID or QR record</small></span><ArrowRight /></button></div></section>
      <section className="surface alerts-surface"><SectionHeading title="Needs attention" action="View all alerts" onAction={() => onNavigate('Alerts')} /><div className="attention"><AlertTriangle /><div><strong>3 suspicious patterns detected</strong><p>Activity does not prove counterfeiting, but needs investigation.</p></div></div><div className="alert-preview"><span className="severity high">High</span><span>Duplicate QR scans</span><strong>OR-2406-C</strong></div><div className="alert-preview"><span className="severity medium">Medium</span><span>Implausible location change</span><strong>NV-2407-A</strong></div></section>
    </div>
  </>
}

function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) { return <div className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</div> }
function SectionHeading({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) { return <div className="section-heading"><h2>{title}</h2>{action && <button onClick={onAction}>{action}<ArrowRight /></button>}</div> }
function JourneyStep({ icon: Icon, label, name, done, current }: { icon: typeof Factory; label: string; name: string; done?: boolean; current?: boolean }) { return <div className="journey-step"><div className={`journey-icon ${done ? 'done' : current ? 'current' : ''}`}><Icon /></div><span>{label}</span><strong>{name}</strong></div> }

function Products({ products, onAdd }: { products: Product[]; onAdd: () => void }) {
  const [query, setQuery] = useState(''); const [filter, setFilter] = useState('All statuses')
  const filtered = useMemo(() => products.filter((p) => `${p.id} ${p.name} ${p.batch} ${p.manufacturer}`.toLowerCase().includes(query.toLowerCase()) && (filter === 'All statuses' || p.status === filter)), [products, query, filter])
  return <><PageHeader eyebrow="PRODUCT REGISTRY" title="Products" description="A record of the products and batches currently tracked in your trust fabric." action={<button className="primary-button" onClick={onAdd}><Plus />Register product</button>} /><section className="surface table-surface"><div className="table-toolbar"><div className="search-field"><Search /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search product ID, name, batch..." aria-label="Search products" /></div><select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by status"><option>All statuses</option><option>Verified</option><option>In transit</option><option>Review</option></select></div><div className="demo-note"><CircleHelp /> Demonstration data · Product records shown here are simulated and not connected to a live registry.</div><div className="table-wrap"><table><thead><tr><th>Product ID</th><th>Product name</th><th>Batch</th><th>Manufacturer</th><th>Recorded custodian</th><th>Status</th><th>Last updated</th></tr></thead><tbody>{filtered.map((product) => <tr key={product.id}><td><strong className="mono">{product.id}</strong></td><td><div className="product-cell"><ProductThumb product={product} /><span>{product.name}</span></div></td><td className="mono">{product.batch}</td><td>{product.manufacturer}</td><td>{product.custodian}</td><td><StatusBadge status={product.status} /></td><td>{product.updated}</td></tr>)}</tbody></table></div></section></>
}

function Verification() {
  const [id, setId] = useState(''); const [result, setResult] = useState<Product | null>(null); const [searched, setSearched] = useState(false)
  const verify = () => { const match = initialProducts.find((product) => product.id.toLowerCase() === id.trim().toLowerCase()); setResult(match ?? null); setSearched(true) }
  return <><PageHeader eyebrow="RECORD VERIFICATION" title="QR Verification" description="Check whether a product's digital record is consistent with its recorded supply-chain history." /><div className="verification-grid"><section className="surface scan-surface"><div className="scan-context"><img src={scanImage} alt="Handheld scanner reading a package barcode" onError={(event) => { event.currentTarget.style.display = 'none' }} /><span>Physical scan context</span></div><div className="scan-frame"><QrCode /><span className="scan-corner top-left" /><span className="scan-corner top-right" /><span className="scan-corner bottom-left" /><span className="scan-corner bottom-right" /></div><h2>Scan product QR</h2><p>Use a connected scanner or camera to read the product identifier.</p><button className="secondary-button" onClick={() => { setId('TT-AX4-9021'); setResult(initialProducts[0]); setSearched(true) }}><QrCode />Simulate scan</button><div className="or-divider"><span>or enter manually</span></div><div className="manual-entry"><input value={id} onChange={(e) => setId(e.target.value)} placeholder="e.g. TT-AX4-9021" aria-label="Product ID" onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && e.keyCode !== 229) verify() }} /><button className="primary-button" onClick={verify}><Search />Verify</button></div><small className="field-help">Try TT-AX4-9021 or TT-OR7-4402</small></section><section className="surface result-surface">{!searched ? <div className="empty-result"><FileSearch /><h2>Verification result</h2><p>Enter a product ID to view its authorized record and checkpoint history.</p></div> : result ? <><div className="result-header"><div><span className="eyebrow">MATCH FOUND</span><h2>Record is consistent</h2></div><span className="verified-seal"><CheckCircle2 />Verified record</span></div><div className="identity-grid"><div className="identity-product"><ProductThumb product={result} large /><span><span>Product</span><strong>{result.name}</strong></span></div><div><span>Product ID</span><strong className="mono">{result.id}</strong></div><div><span>Batch</span><strong className="mono">{result.batch}</strong></div><div><span>Manufacturer</span><strong>{result.manufacturer}</strong></div></div><div className="timeline"><TimelineItem title="Recorded by manufacturer" detail={`${result.manufacturer} · Jun 12, 08:15`} done /><TimelineItem title="Received at warehouse" detail="Harborpoint Warehouse · Jun 14, 13:40" done /><TimelineItem title="Custody transferred" detail={`${result.custodian} · Today, 09:42`} done /></div><div className="disclaimer"><CircleHelp /><span>This confirms the QR-linked record is consistent with recorded events. It does not, by itself, authenticate the physical product or packaging.</span></div></> : <div className="empty-result"><X /><h2>No matching record</h2><p>No authorized record was found for <strong>{id}</strong>. Check the identifier or investigate through your registry administrator.</p></div>}</section></div></>
}
function TimelineItem({ title, detail, done }: { title: string; detail: string; done?: boolean }) { return <div className="timeline-item"><div className={`timeline-dot ${done ? 'done' : ''}`}>{done && <Check />}</div><div><strong>{title}</strong><span>{detail}</span></div></div> }

function SupplyChain() { return <><PageHeader eyebrow="MOVEMENT TRACKING" title="Supply Chain" description="Follow the recorded custody path for active products and shipments." action={<button className="secondary-button"><Truck />Export shipment log</button>} /><section className="surface shipment-summary"><div><span className="eyebrow">ACTIVE SHIPMENT</span><h2>TT-NV2-1184 · Novera Vitamin D3</h2><p>Batch NV-2407-A · Expected arrival Jun 21, 2024</p></div><StatusBadge status="In transit" /></section><section className="surface checkpoints"><SectionHeading title="Custody checkpoints" /><div className="checkpoint-track"><Checkpoint number="01" icon={Factory} title="Manufacturer" place="Novera Health" date="Jun 12 · 08:15" state="Complete" /><Checkpoint number="02" icon={Box} title="Warehouse" place="Harborpoint Warehouse" date="Jun 14 · 13:40" state="Complete" /><Checkpoint number="03" icon={Truck} title="Distributor" place="Deltaway Distribution" date="Jun 18 · 08:16" state="Current" /><Checkpoint number="04" icon={MapPin} title="Retailer" place="Northline Retail" date="Expected Jun 21" state="Pending" /></div></section><div className="detail-grid"><section className="surface detail-surface"><SectionHeading title="Shipment details" /><div className="detail-rows"><div><span>Recorded custodian</span><strong>Deltaway Distribution</strong></div><div><span>Shipment reference</span><strong className="mono">SHP-8841-NV</strong></div><div><span>Units in shipment</span><strong>420 units</strong></div><div><span>Last event recorded</span><strong>Today, 08:16</strong></div></div></section><section className="surface detail-surface"><SectionHeading title="Record integrity" /><div className="integrity-score"><div className="score-ring">98<span>%</span></div><div><strong>Consistent so far</strong><p>All custody transfers match authorized records.</p></div></div><div className="integrity-foot"><CheckCircle2 />No unresolved record conflicts</div></section></div></> }
function Checkpoint({ number, icon: Icon, title, place, date, state }: { number: string; icon: typeof Factory; title: string; place: string; date: string; state: string }) { return <div className={`checkpoint ${state.toLowerCase()}`}><div className="checkpoint-line"><span>{number}</span><div className="checkpoint-icon"><Icon /></div></div><span className="checkpoint-state">{state}</span><strong>{title}</strong><span>{place}</span><small>{date}</small></div> }

function Alerts() { const [reviewed, setReviewed] = useState<string[]>([]); const alerts = [{ id: 'ALT-042', severity: 'High', product: 'TT-OR7-4402', pattern: 'Duplicate QR scans', evidence: '3 scans across 2 regions in 42 minutes', time: 'Yesterday, 18:24' }, { id: 'ALT-039', severity: 'Medium', product: 'TT-NV2-1184', pattern: 'Implausible location change', evidence: 'Warehouse to retailer in 11 minutes', time: 'Jun 18, 09:10' }, { id: 'ALT-036', severity: 'Medium', product: 'TT-CL8-7210', pattern: 'Unauthorized custody transfer', evidence: 'New custodian is not on batch route', time: 'Jun 17, 14:39' }]; return <><PageHeader eyebrow="INVESTIGATION QUEUE" title="Alerts" description="Review patterns that may indicate record conflicts or unauthorized activity." /><div className="alert-banner"><AlertTriangle /><div><strong>Suspicious patterns are signals, not proof.</strong><span>Investigate the evidence and verify with physical inspection before drawing conclusions about counterfeiting.</span></div></div><section className="surface table-surface"><div className="table-toolbar"><div><h2 className="table-title">Open investigations <span>3 total</span></h2></div><button className="secondary-button"><ClipboardCheck />Export report</button></div><div className="table-wrap"><table><thead><tr><th>Severity</th><th>Product ID</th><th>Detected pattern</th><th>Evidence</th><th>Detected</th><th>Review</th></tr></thead><tbody>{alerts.map((alert) => { const done = reviewed.includes(alert.id); return <tr key={alert.id} className={done ? 'row-reviewed' : ''}><td><span className={`severity ${alert.severity.toLowerCase()}`}>{alert.severity}</span></td><td><strong className="mono">{alert.product}</strong><small className="row-id">{alert.id}</small></td><td><strong>{alert.pattern}</strong></td><td>{alert.evidence}</td><td>{alert.time}</td><td><button className={`review-button ${done ? 'done' : ''}`} onClick={() => setReviewed((current) => done ? current.filter((id) => id !== alert.id) : [...current, alert.id])}>{done ? <><Check />Reviewed</> : 'Mark reviewed'}</button></td></tr>})}</tbody></table></div></section></> }

function PlaceholderPage({ page }: { page: PageKey }) { return <><PageHeader eyebrow={page.toUpperCase()} title={page} description="This workspace is ready for your organization’s connected records and operating rules." /><section className="surface empty-page"><Settings /><h2>{page} workspace</h2><p>This demonstration view focuses on the core verification and operations workflows. Connect a backend to activate this area.</p></section></> }

export default function Page() { const [active, setActive] = useState<PageKey>('Overview'); const [mobileOpen, setMobileOpen] = useState(false); const [products, setProducts] = useState(initialProducts); const addProduct = () => { const product: Product = { id: `TT-DEMO-${String(products.length + 1).padStart(4, '0')}`, name: 'New demonstration product', batch: 'DEMO-2408', manufacturer: 'TraceTrust Demo', custodian: 'TraceTrust Demo', status: 'Verified', updated: 'Just now' }; setProducts((current) => [product, ...current]); setActive('Products') }; const navigate = (page: PageKey) => { setActive(page); setMobileOpen(false) }; return <div className="app-shell"><div className={`mobile-overlay ${mobileOpen ? 'show' : ''}`} onClick={() => setMobileOpen(false)} /><div className={`sidebar-wrap ${mobileOpen ? 'open' : ''}`}><Sidebar active={active} onNavigate={navigate} /></div><div className="main-shell"><Topbar active={active} onMenu={() => setMobileOpen(true)} /><main className="workspace">{active === 'Overview' && <Overview onNavigate={navigate} />}{active === 'Products' && <Products products={products} onAdd={addProduct} />}{active === 'QR Verification' && <Verification />}{active === 'Supply Chain' && <SupplyChain />}{active === 'Alerts' && <Alerts />}{(active === 'Event History' || active === 'Settings') && <PlaceholderPage page={active} />}</main></div></div> }
