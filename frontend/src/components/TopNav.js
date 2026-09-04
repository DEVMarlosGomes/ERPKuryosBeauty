import { useEffect, useMemo, useRef, useState } from "react";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

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

export default function TopNav({ scrollContainerRef }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { dark, setDark } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [hidden, setHidden] = useState(false);
  const lastScrollByTarget = useRef(new WeakMap());

  const visibleGroups = useMemo(
    () => NAV_GROUPS.filter(group => isVisibleForRole(group, user?.role)),
    [user?.role]
  );
  const standalone = useMemo(
    () => STANDALONE.filter(item => isVisibleForRole(item, user?.role)),
    [user?.role]
  );

  useEffect(() => {
    setMobileOpen(false);
    setHidden(false);
  }, [location.pathname]);

  useEffect(() => {
    const getScrollElement = (eventTarget) => {
      if (!eventTarget || eventTarget === document || eventTarget === window) {
        return scrollContainerRef?.current || document.scrollingElement || document.documentElement;
      }
      return eventTarget;
    };

    const getScrollTop = (target) => {
      if (!target) return 0;
      if (target === document || target === window) {
        return window.scrollY || document.documentElement.scrollTop || 0;
      }
      return Number(target.scrollTop || 0);
    };

    const onScroll = (event) => {
      if (location.pathname === "/dashboard") {
        setHidden(false);
        return;
      }
      const target = getScrollElement(event?.target);
      const current = getScrollTop(target);
      const lastTop = lastScrollByTarget.current.get(target) || 0;
      if (current < 16) {
        setHidden(false);
      } else if (current > lastTop + 8) {
        setHidden(true);
      } else if (current < lastTop - 8) {
        setHidden(false);
      }
      lastScrollByTarget.current.set(target, current);
    };

    const main = scrollContainerRef?.current;
    if (main) {
      lastScrollByTarget.current.set(main, main.scrollTop || 0);
    }
    window.addEventListener("scroll", onScroll, { passive: true, capture: true });
    return () => window.removeEventListener("scroll", onScroll, { capture: true });
  }, [location.pathname, scrollContainerRef]);

  const go = (path) => {
    navigate(path);
    setMobileOpen(false);
  };

  const navClass = hidden ? "-translate-y-full" : "translate-y-0";

  return (
    <>
      <header
        className={`fixed inset-x-0 top-0 z-50 border-b border-border/70 bg-background/78 shadow-sm backdrop-blur-2xl transition-transform duration-300 ${navClass}`}
        data-testid="top-nav"
      >
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-3 px-4 md:h-16 md:px-6">
          <button
            type="button"
            onClick={() => go("/dashboard")}
            className="flex shrink-0 items-center gap-2 rounded-md px-1 py-1 text-left hover:bg-muted/60"
            data-testid="top-nav-logo"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[#0f2044] text-sm font-semibold text-white shadow-sm ring-1 ring-white/10">
              K
            </div>
            <div className="hidden leading-none sm:block">
              <p className="text-sm font-semibold uppercase tracking-normal">Kuryos</p>
              <p className="mt-0.5 text-[10px] uppercase text-muted-foreground">ERP</p>
            </div>
          </button>

          <nav className="hidden min-w-0 flex-1 items-center justify-center gap-1 lg:flex" aria-label="Navegacao principal">
            {visibleGroups.map((group, index) => (
              <div key={group.key} className="contents">
                <TopNavGroup group={group} active={isGroupActive(group, location.pathname)} go={go} />
                {index === 0 && standalone.map(item => (
                  <StandaloneNavItem key={item.key} item={item} pathname={location.pathname} go={go} />
                ))}
              </div>
            ))}
            {visibleGroups.length === 0 && standalone.map(item => (
              <StandaloneNavItem key={item.key} item={item} pathname={location.pathname} go={go} />
            ))}
          </nav>

          <div className="ml-auto hidden items-center gap-1 lg:flex">
            <Button variant="ghost" size="icon" className="h-9 w-9 rounded-md" title="Buscar">
              <Search className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 rounded-md"
              onClick={() => setDark(!dark)}
              title={dark ? "Modo Claro" : "Modo Escuro"}
              data-testid="theme-toggle"
            >
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="h-9 max-w-[210px] rounded-md px-2">
                  <span className="truncate text-xs">{user?.name || "Usuario"}</span>
                  <ChevronDown className="ml-1 h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <p className="truncate">{user?.name || "Usuario"}</p>
                  <p className="truncate text-xs font-normal text-muted-foreground">{user?.role || "perfil"}</p>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => logout()} className="text-red-600 focus:text-red-600">
                  <LogOut className="h-4 w-4" />
                  Sair
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <Button
            variant="ghost"
            size="icon"
            className="ml-auto h-9 w-9 rounded-md lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Abrir menu"
            data-testid="mobile-menu-btn"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </div>
      </header>

      {mobileOpen && (
        <div className="fixed inset-0 z-[60] lg:hidden" data-testid="mobile-topnav-drawer">
          <button className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => setMobileOpen(false)} aria-label="Fechar menu" />
          <aside className="absolute right-0 top-0 flex h-full w-[min(88vw,360px)] flex-col border-l border-border/70 bg-background/95 p-4 shadow-2xl backdrop-blur-xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[#0f2044] text-sm font-semibold text-white">K</div>
                <div>
                  <p className="text-sm font-semibold uppercase">Kuryos</p>
                  <p className="text-[10px] uppercase text-muted-foreground">ERP</p>
                </div>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setMobileOpen(false)}>
                <X className="h-5 w-5" />
              </Button>
            </div>
            <div className="mt-5 flex-1 space-y-4 overflow-y-auto">
              {visibleGroups.map((group, index) => {
                const GroupIcon = group.icon;
                return (
                  <div key={group.key} className="space-y-3">
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 px-2 text-xs font-semibold uppercase text-muted-foreground">
                        <GroupIcon className="h-4 w-4" />
                        {group.label}
                      </div>
                      <div className="grid gap-1">
                        {group.children.map(child => <MobileLink key={child.path} item={child} go={go} pathname={location.pathname} />)}
                      </div>
                    </div>
                    {index === 0 && standalone.map(item => <MobileLink key={item.key} item={item} go={go} pathname={location.pathname} />)}
                  </div>
                );
              })}
              {visibleGroups.length === 0 && standalone.map(item => <MobileLink key={item.key} item={item} go={go} pathname={location.pathname} />)}
            </div>
            <div className="mt-4 grid gap-2 border-t pt-4">
              <Button variant="outline" onClick={() => setDark(!dark)} className="justify-start gap-2">
                {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                {dark ? "Modo Claro" : "Modo Escuro"}
              </Button>
              <Button variant="ghost" onClick={logout} className="justify-start gap-2 text-red-600 hover:text-red-600">
                <LogOut className="h-4 w-4" />
                Sair
              </Button>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}

function TopNavGroup({ group, active, go }) {
  const Icon = group.icon;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant={active ? "secondary" : "ghost"} size="sm" className="h-9 gap-2 rounded-md px-3 text-sm">
          <Icon className="h-4 w-4" />
          {group.label}
          <ChevronDown className="h-3.5 w-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="center" className="w-64">
        <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {group.children.map(child => {
          const ChildIcon = child.icon;
          return (
            <DropdownMenuItem key={child.path} onClick={() => go(child.path)} className="cursor-pointer">
              {ChildIcon && <ChildIcon className="h-4 w-4" />}
              <span>{child.label}</span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function StandaloneNavItem({ item, pathname, go }) {
  const Icon = item.icon;
  const active = pathname === item.path || pathname.startsWith(`${item.path}/`);
  return (
    <Button
      variant={active ? "secondary" : "ghost"}
      size="sm"
      className="h-9 gap-2 rounded-md px-3 text-sm"
      onClick={() => go(item.path)}
    >
      <Icon className="h-4 w-4" />
      {item.label}
    </Button>
  );
}

function MobileLink({ item, go, pathname }) {
  const Icon = item.icon;
  const active = pathname === item.path || pathname.startsWith(`${item.path}/`);
  return (
    <button
      type="button"
      onClick={() => go(item.path)}
      className={`flex min-h-10 w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm ${
        active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      {Icon && <Icon className="h-4 w-4 shrink-0" />}
      <span className="min-w-0 truncate">{item.label}</span>
    </button>
  );
}
