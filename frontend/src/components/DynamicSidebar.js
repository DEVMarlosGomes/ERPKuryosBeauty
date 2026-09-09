import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/App";
import {
  BarChart3,
  BookOpen,
  BriefcaseBusiness,
  Building2,
  Calendar,
  CheckSquare,
  ChevronDown,
  ChevronLeft,
  ClipboardList,
  Database,
  Factory,
  FileText,
  FlaskConical,
  History,
  LogOut,
  Menu,
  Moon,
  Package,
  Receipt,
  Search,
  ShieldCheck,
  ShoppingCart,
  Sun,
  Tags,
  Truck,
  Users,
  Warehouse,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

const NAV_GROUPS = [
  {
    key: "comercial",
    label: "Comercial",
    icon: BriefcaseBusiness,
    basePaths: ["/crm", "/pipeline", "/compras", "/kickoff", "/kickoffs", "/contratos", "/cadastros", "/orders", "/pedidos", "/pcp/matriz-insumos"],
    roles: ["admin", "vendedor", "sales_ops", "sucesso_cliente", "gestor", "compras", "lider_pd", "qa", "engenharia_produto"],
    children: [
      { label: "CRM", path: "/crm/clients", icon: Building2 },
      { label: "Compras", path: "/compras", icon: Package },
      { label: "Kickoff", path: "/kickoffs", icon: ClipboardList },
      { label: "Contratos", path: "/contratos", icon: FileText },
      { label: "Cadastros", path: "/cadastros", icon: Tags },
      { label: "Orcamentos", path: "/crm/orcamentos", icon: Receipt },
      { label: "Matriz de Insumos", path: "/pcp/matriz-insumos", icon: Database },
      { label: "Pedidos", path: "/orders", icon: ShoppingCart },
    ],
  },
  {
    key: "financeiro",
    label: "Financeiro",
    icon: Receipt,
    basePaths: ["/faturamento", "/rh", "/team"],
    roles: ["admin", "sales_ops", "compras", "gestor"],
    children: [
      { label: "Faturamento", path: "/faturamento", icon: Receipt },
      { label: "RH", path: "/rh", icon: Users },
    ],
  },
  {
    key: "pd",
    label: "P&D",
    icon: FlaskConical,
    basePaths: ["/pd", "/homologacoes", "/crm/skus"],
    roles: ["admin", "lider_pd", "formulador", "qa", "engenharia_produto", "sales_ops", "gestor"],
    children: [
      { label: "Pipeline", path: "/pd", icon: ClipboardList },
      { label: "Banco de Formulas", path: "/pd/formulas", icon: BookOpen },
      { label: "Homologacoes", path: "/pd/homologacao", icon: ShieldCheck },
      { label: "Banco de Custos", path: "/pd/catalog", icon: Database },
      { label: "Estoque Lab", path: "/pd/estoque", icon: Warehouse },
      { label: "SKUs e Catalogos", path: "/crm/skus", icon: Package },
      { label: "Relatorios", path: "/pd/relatorios", icon: BarChart3 },
    ],
  },
  {
    key: "logistica",
    label: "Logistica",
    icon: Truck,
    basePaths: ["/logistica", "/estoque", "/recebimento", "/expedicao"],
    roles: ["admin", "lider_pd", "formulador", "qa", "engenharia_produto", "compras", "sales_ops", "gestor"],
    children: [
      { label: "Logistica", path: "/logistica", icon: Truck },
      { label: "Recebimento / CQ", path: "/recebimento", icon: ShieldCheck },
      { label: "Estoque / WMS", path: "/estoque", icon: Warehouse },
      { label: "Historico WMS", path: "/estoque/movimentacao", icon: History },
      { label: "Expedicao / Romaneio", path: "/expedicao", icon: Truck },
      { label: "Agendamentos", path: "/logistica/agendamentos", icon: Calendar },
    ],
  },
  {
    key: "pcp",
    label: "PCP",
    icon: Factory,
    basePaths: ["/pcp"],
    excludePaths: ["/pcp/matriz-insumos"],
    roles: ["admin", "lider_pd", "formulador", "qa", "engenharia_produto", "compras", "gestor", "sales_ops"],
    children: [
      { label: "Dashboard Diario", path: "/pcp/dashboard", icon: BarChart3 },
      { label: "Historico/Pedidos de Vendas", path: "/pcp/historico", icon: History },
      { label: "PCP / Planejamento", path: "/pcp/planejamento", icon: Calendar },
      { label: "Horizonte de Producao", path: "/pcp/horizonte", icon: BarChart3 },
      { label: "Controle de OPs", path: "/pcp/controle-ops", icon: Factory },
      { label: "Emitir OP", path: "/pcp/emitir-op", icon: FileText },
    ],
  },
];

const STANDALONE = [
  { key: "tasks", label: "Tarefas", path: "/tasks", icon: CheckSquare, roles: null },
];

function isVisibleForRole(item, role) {
  if (!item.roles) return true;
  if (role === "admin") return true;
  return item.roles.includes(role);
}

function isGroupActive(group, pathname) {
  if (group.excludePaths?.some(path => pathname === path || pathname.startsWith(`${path}/`))) {
    return false;
  }
  return group.basePaths.some(path => pathname === path || pathname.startsWith(`${path}/`));
}

function isItemActive(pathname, path) {
  return pathname === path || pathname.startsWith(`${path}/`);
}

export default function DynamicSidebar({ onReservedWidthChange }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { dark, setDark } = useTheme();
  const [hovered, setHovered] = useState(false);
  const [pinnedOpen, setPinnedOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const isDashboard = location.pathname === "/dashboard";

  const visibleGroups = useMemo(
    () => NAV_GROUPS.filter(group => isVisibleForRole(group, user?.role)),
    [user?.role]
  );
  const standalone = useMemo(
    () => STANDALONE.filter(item => isVisibleForRole(item, user?.role)),
    [user?.role]
  );

  const reservedOpen = isDashboard || pinnedOpen;
  const expanded = reservedOpen || hovered || mobileOpen;

  useEffect(() => {
    setHovered(false);
    setMobileOpen(false);
    if (location.pathname !== "/dashboard") {
      setPinnedOpen(false);
    }
  }, [location.pathname]);

  useEffect(() => {
    onReservedWidthChange?.(reservedOpen);
  }, [onReservedWidthChange, reservedOpen]);

  const go = (path) => {
    navigate(path);
    setMobileOpen(false);
  };

  return (
    <>
      <header className="fixed inset-x-0 top-0 z-50 flex h-14 items-center justify-between border-b border-border/70 bg-background/90 px-4 shadow-sm backdrop-blur-xl lg:hidden">
        <button type="button" onClick={() => go("/dashboard")} className="flex min-w-0 items-center gap-2">
          <BrandMark />
          <span className="truncate text-sm font-semibold uppercase">Kuryos ERP</span>
        </button>
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-md" onClick={() => setMobileOpen(true)} aria-label="Abrir menu">
          <Menu className="h-5 w-5" />
        </Button>
      </header>

      <aside
        className={`fixed inset-y-0 left-0 z-50 hidden border-r border-border/70 bg-background/88 shadow-xl backdrop-blur-2xl transition-[width] duration-300 ease-out lg:flex lg:flex-col ${expanded ? "w-[280px]" : "w-[76px]"}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        data-testid="dynamic-sidebar"
      >
        <SidebarContent
          expanded={expanded}
          pinnedOpen={pinnedOpen}
          setPinnedOpen={setPinnedOpen}
          isDashboard={isDashboard}
          visibleGroups={visibleGroups}
          standalone={standalone}
          pathname={location.pathname}
          go={go}
          user={user}
          logout={logout}
          dark={dark}
          setDark={setDark}
        />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-[60] lg:hidden" data-testid="mobile-sidebar-drawer">
          <button className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => setMobileOpen(false)} aria-label="Fechar menu" />
          <aside className="absolute left-0 top-0 flex h-full w-[min(88vw,340px)] flex-col border-r border-border/70 bg-background/96 shadow-2xl backdrop-blur-xl">
            <SidebarContent
              expanded={expanded}
              pinnedOpen={pinnedOpen}
              setPinnedOpen={setPinnedOpen}
              isDashboard={isDashboard}
              visibleGroups={visibleGroups}
              standalone={standalone}
              pathname={location.pathname}
              go={go}
              user={user}
              logout={logout}
              dark={dark}
              setDark={setDark}
              mobile
              closeMobile={() => setMobileOpen(false)}
            />
          </aside>
        </div>
      )}
    </>
  );
}

function SidebarContent({
  expanded,
  pinnedOpen,
  setPinnedOpen,
  isDashboard,
  visibleGroups,
  standalone,
  pathname,
  go,
  user,
  logout,
  dark,
  setDark,
  mobile = false,
  closeMobile,
}) {
  return (
    <>
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-border/70 px-4">
        <button type="button" onClick={() => go("/dashboard")} className="flex min-w-0 flex-1 items-center gap-3 rounded-md text-left">
          <BrandMark />
          <span className={`min-w-0 overflow-hidden transition-opacity duration-200 ${expanded ? "opacity-100" : "opacity-0"}`}>
            <span className="block truncate text-sm font-semibold uppercase">Kuryos</span>
            <span className="block truncate text-[10px] uppercase text-muted-foreground">ERP</span>
          </span>
        </button>
        {mobile ? (
          <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={closeMobile} aria-label="Fechar menu">
            <X className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            className={`h-8 w-8 shrink-0 rounded-md transition-opacity ${expanded ? "opacity-100" : "pointer-events-none opacity-0"}`}
            onClick={() => setPinnedOpen(!pinnedOpen)}
            title={pinnedOpen || isDashboard ? "Recolher nos modulos" : "Fixar aberto"}
          >
            <ChevronLeft className={`h-4 w-4 transition-transform ${pinnedOpen || isDashboard ? "" : "rotate-180"}`} />
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 py-4">
        <div className="space-y-2">
          {standalone.map(item => (
            <SidebarLink key={item.key} item={item} pathname={pathname} go={go} expanded={expanded} />
          ))}
        </div>

        <nav className="mt-4 space-y-4" aria-label="Navegacao principal">
          {visibleGroups.map(group => (
            <SidebarGroup key={group.key} group={group} pathname={pathname} go={go} expanded={expanded} />
          ))}
        </nav>
      </div>

      <div className="shrink-0 border-t border-border/70 p-3">
        <SidebarAction icon={Search} label="Buscar" expanded={expanded} />
        <button
          type="button"
          onClick={() => setDark(!dark)}
          className="mt-1 flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
          title={dark ? "Modo Claro" : "Modo Escuro"}
        >
          {dark ? <Sun className="h-4 w-4 shrink-0" /> : <Moon className="h-4 w-4 shrink-0" />}
          <span className={`min-w-0 truncate transition-opacity ${expanded ? "opacity-100" : "opacity-0"}`}>
            {dark ? "Modo Claro" : "Modo Escuro"}
          </span>
        </button>
        <div className={`mt-3 overflow-hidden border-t border-border/70 pt-3 transition-opacity ${expanded ? "opacity-100" : "opacity-0"}`}>
          <p className="truncate text-xs font-medium">{user?.name || "Usuario"}</p>
          <p className="truncate text-[11px] text-muted-foreground">{user?.role || "perfil"}</p>
          <button
            type="button"
            onClick={logout}
            className="mt-2 flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-red-600 hover:bg-red-500/10"
          >
            <LogOut className="h-4 w-4 shrink-0" />
            <span className="truncate">Sair</span>
          </button>
        </div>
      </div>
    </>
  );
}

function SidebarGroup({ group, pathname, go, expanded }) {
  const Icon = group.icon;
  const active = isGroupActive(group, pathname);
  const [open, setOpen] = useState(active);

  useEffect(() => {
    if (active) setOpen(true);
  }, [active]);

  if (!expanded) {
    return (
      <div className="flex justify-center">
        <button
          type="button"
          onClick={() => go(group.children[0]?.path || "/dashboard")}
          className={`flex h-11 w-11 items-center justify-center rounded-md ${active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
          title={group.label}
        >
          <Icon className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className={`flex h-10 w-full min-w-0 items-center gap-3 rounded-md px-3 text-left text-sm font-medium ${active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
        >
          <Icon className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1 truncate">{group.label}</span>
          <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 space-y-1 pl-2">
        {group.children.map(child => (
          <SidebarLink key={child.path} item={child} pathname={pathname} go={go} expanded={expanded} child />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

function SidebarLink({ item, pathname, go, expanded, child = false }) {
  const Icon = item.icon;
  const active = isItemActive(pathname, item.path);
  return (
    <button
      type="button"
      onClick={() => go(item.path)}
      className={`flex h-10 w-full min-w-0 items-center gap-3 rounded-md px-3 text-left text-sm ${
        active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"
      } ${child ? "text-[13px]" : ""}`}
      title={item.label}
    >
      {Icon && <Icon className="h-4 w-4 shrink-0" />}
      <span className={`min-w-0 truncate transition-opacity ${expanded ? "opacity-100" : "opacity-0"}`}>{item.label}</span>
    </button>
  );
}

function SidebarAction({ icon: Icon, label, expanded }) {
  return (
    <button
      type="button"
      className="flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
      title={label}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className={`min-w-0 truncate transition-opacity ${expanded ? "opacity-100" : "opacity-0"}`}>{label}</span>
    </button>
  );
}

function BrandMark() {
  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[#0f2044] text-sm font-semibold text-white shadow-sm ring-1 ring-white/10">
      K
    </div>
  );
}
