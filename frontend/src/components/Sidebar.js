import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/App";
import {
    LayoutDashboard, Kanban, Users, LogOut, Moon, Sun, FlaskConical, Building2,
    Package, ChevronDown, ChevronRight, ShieldCheck, BarChart3, Warehouse, ClipboardList,
    CheckSquare, History, BookOpen, Database, Menu, X, ShoppingCart, FileText, Microscope, Factory,
    Truck, Receipt, Calendar, ArrowLeftRight, PanelLeftClose, PanelLeftOpen, Tags
} from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotificationPanel from "@/components/NotificationPanel";
import { useState, useEffect, useMemo, useRef } from "react";

const NAV_MODULES = [
    {
        key: "tasks",
        type: "link",
        path: "/tasks",
        label: "Tarefas",
        icon: CheckSquare,
        roles: null, // all roles
    },
    {
        key: "dashboard",
        type: "link",
        path: "/dashboard",
        label: "Dashboard",
        icon: LayoutDashboard,
        roles: null,
    },
    {
        key: "crm",
        type: "group",
        label: "CRM Comercial",
        icon: Building2,
        basePaths: ["/crm/clients", "/crm/projects", "/crm/samples", "/crm/orcamentos"],
        roles: ["admin", "vendedor", "sales_ops", "sucesso_cliente", "gestor"],
        children: [
            { path: "/crm/clients", label: "Pipeline Clientes" },
            { path: "/crm/projects", label: "Projetos" },
            { path: "/crm/samples", label: "Amostras" },
            { path: "/crm/orcamentos", label: "Orcamentos", icon: FileText },
        ],
    },
    {
        key: "kickoffs",
        type: "link",
        path: "/kickoffs",
        label: "Kickoffs",
        icon: ClipboardList,
        roles: ["admin", "vendedor", "sales_ops", "formulador", "qa", "lider_pd", "engenharia_produto", "sucesso_cliente", "gestor"],
    },
    {
        key: "cadastros",
        type: "link",
        path: "/cadastros",
        label: "Cadastros",
        icon: Tags,
        roles: ["admin", "vendedor", "sales_ops", "sucesso_cliente", "lider_pd", "formulador", "qa", "engenharia_produto", "compras", "gestor"],
    },
    {
        key: "pd",
        type: "group",
        label: "P&D",
        icon: FlaskConical,
        basePaths: ["/pd", "/pd/formulas", "/pd/catalog", "/pd/estoque", "/crm/skus", "/pd/homologacao", "/pd/relatorios"],
        roles: ["admin", "lider_pd", "formulador", "qa", "engenharia_produto", "sales_ops", "gestor"],
        children: [
            { path: "/pd", label: "Pipeline P&D", icon: ClipboardList },
            { path: "/pd/formulas", label: "Banco de Fórmulas", icon: BookOpen },
            { path: "/pd/homologacao", label: "Homologações", icon: ShieldCheck },
            { path: "/pd/catalog", label: "Banco de Custos", icon: Database },
            { path: "/pd/estoque", label: "Estoque Lab", icon: Warehouse },
            { path: "/crm/skus", label: "SKUs / Catálogo", icon: Package },
            { path: "/pd/relatorios", label: "Relatórios", icon: BarChart3 },
        ],
    },
    {
        key: "logistica",
        type: "group",
        label: "Logistica",
        icon: Truck,
        basePaths: ["/logistica", "/estoque", "/recebimento", "/expedicao"],
        roles: ["admin", "lider_pd", "formulador", "qa", "engenharia_produto", "compras", "sales_ops", "gestor"],
        children: [
            { path: "/logistica", label: "Visao Geral", icon: Truck },
            { path: "/recebimento", label: "Recebimento / CQ", icon: Package },
            { path: "/estoque", label: "Estoque / WMS", icon: Warehouse },
            { path: "/estoque/movimentacao", label: "Historico WMS", icon: ArrowLeftRight },
            { path: "/expedicao", label: "Expedicao / Romaneio", icon: Truck },
            { path: "/logistica/agendamentos", label: "Agendamentos", icon: Calendar },
        ],
    },
    {
        key: "cq",
        type: "group",
        label: "Controle de Qualidade",
        icon: Microscope,
        basePaths: ["/cq", "/cq/retrabalho"],
        roles: ["admin", "qa", "lider_pd", "formulador", "engenharia_produto", "compras", "sales_ops"],
        children: [
            { path: "/cq",                       label: "Dashboard CQ" },
            { path: "/cq/registros-analise",     label: "Registros de Análise" },
            { path: "/cq/checklists",            label: "Checklists" },
            { path: "/cq/rncs",                  label: "Não Conformidades" },
            { path: "/cq/retencoes",             label: "Retenções" },
            { path: "/cq/instrumentos",          label: "Instrumentos" },
            { path: "/cq/retrabalho",            label: "Retrabalho" },
        ],
    },
    {
        key: "orders",
        type: "link",
        path: "/orders",
        label: "Pedidos",
        icon: ShoppingCart,
        roles: null,
    },
    {
        key: "pcp",
        type: "group",
        label: "PCP",
        icon: Calendar,
        basePaths: ["/pcp"],
        roles: ["admin", "lider_pd", "formulador", "qa", "engenharia_produto", "compras", "gestor", "sales_ops"],
        children: [
            { path: "/pcp/dashboard", label: "Dashboard Diário", icon: LayoutDashboard },
            { path: "/pcp/historico", label: "Histórico/Pedidos Vendas", icon: History },
            { path: "/pcp/planejamento", label: "PCP / Planejamento", icon: Calendar },
            { path: "/pcp/horizonte", label: "Horizonte de Produção", icon: BarChart3 },
            { path: "/pcp/controle-ops", label: "Controle de OPs", icon: Factory },
            { path: "/pcp/emitir-op", label: "Emitir OP", icon: FileText },
        ],
    },
    {
        key: "matriz-insumos",
        type: "link",
        path: "/pcp/matriz-insumos",
        label: "Matriz de Insumos",
        icon: Database,
        roles: ["admin", "lider_pd", "formulador", "qa", "engenharia_produto", "compras", "gestor", "sales_ops"],
    },
    {
        key: "faturamento",
        type: "link",
        path: "/faturamento",
        label: "Faturamento",
        icon: Receipt,
        roles: ["admin", "sales_ops", "compras", "gestor"],
    },
    {
        key: "compras",
        type: "group",
        label: "Compras",
        icon: Package,
        basePaths: ["/compras"],
        roles: ["admin", "compras", "engenharia_produto", "lider_pd", "qa", "sales_ops"],
        children: [
            { path: "/compras", label: "Esteira Compras" },
            { path: "/compras/mrp", label: "Solicitacoes / MRP" },
            { path: "/compras/itens", label: "Itens / Cotacoes" },
            { path: "/compras/fornecedores", label: "Fornecedores" },
            { path: "/compras/pos", label: "Pedidos de Compra" },
            { path: "/compras/estoque-projetado", label: "Estoque Projetado" },
        ],
    },
    {
        key: "contratos",
        type: "link",
        path: "/contratos",
        label: "Contratos CGI",
        icon: FileText,
        roles: ["admin", "sales_ops", "vendedor", "compras", "lider_pd", "qa", "engenharia_produto", "sucesso_cliente"],
    },
    {
        key: "audit",
        type: "link",
        path: "/audit",
        label: "Auditoria",
        icon: History,
        roles: ["admin", "lider_pd", "qa", "sales_ops", "gestor"],
    },
    {
        key: "team",
        type: "link",
        path: "/team",
        label: "Equipe",
        icon: Users,
        roles: ["admin"],
    },
];

function isVisibleForRole(item, role) {
    if (!item.roles) return true;
    if (role === "admin") return true;
    return item.roles.includes(role);
}

export default function Sidebar() {
    const location = useLocation();
    const navigate = useNavigate();
    const { user, logout } = useAuth();
    const { dark, setDark } = useTheme();
    const [mobileOpen, setMobileOpen] = useState(false);
    const [collapsed, setCollapsed] = useState(() => localStorage.getItem("sidebarCollapsed") === "true");
    const navRef = useRef(null);

    const filteredModules = useMemo(
        () => NAV_MODULES.filter((m) => isVisibleForRole(m, user?.role)),
        [user?.role]
    );

    const computeInitialOpen = () => {
        const opens = {};
        for (const mod of filteredModules) {
            if (mod.type === "group") {
                const isIn = mod.basePaths.some(bp => location.pathname === bp || location.pathname.startsWith(bp));
                opens[mod.key] = isIn;
            }
        }
        return opens;
    };
    const [openGroups, setOpenGroups] = useState(computeInitialOpen);

    useEffect(() => {
        setOpenGroups((prev) => {
            const next = { ...prev };
            for (const mod of filteredModules) {
                if (mod.type === "group") {
                    const isIn = mod.basePaths.some(bp => location.pathname === bp || location.pathname.startsWith(bp));
                    if (isIn) next[mod.key] = true;
                }
            }
            return next;
        });
        // close mobile menu on route change
        setMobileOpen(false);
    }, [location.pathname, filteredModules]);

    useEffect(() => {
        localStorage.setItem("sidebarCollapsed", collapsed ? "true" : "false");
    }, [collapsed]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            const activeItem = navRef.current?.querySelector(".sidebar-item.active");
            activeItem?.scrollIntoView({ block: "nearest" });
        }, 50);
        return () => window.clearTimeout(timer);
    }, [location.pathname, collapsed, openGroups]);

    const isActive = (path) => {
        if (location.pathname === path) return true;
        if (path === "/pd" && (location.pathname.startsWith("/pd/") || location.pathname === "/pd")) {
            return location.pathname === "/pd";
        }
        return location.pathname.startsWith(path + "/") && path !== "/";
    };

    const toggleGroup = (key) => {
        if (collapsed) {
            setCollapsed(false);
            setOpenGroups((prev) => ({ ...prev, [key]: true }));
            return;
        }
        setOpenGroups((prev) => ({ ...prev, [key]: !prev[key] }));
    };

    const handleNavigate = (path) => {
        navigate(path);
        setMobileOpen(false);
    };

    const sidebarContent = ({ compact = false } = {}) => (
        <>
            <div className={`flex items-center gap-2 ${compact ? "justify-center p-3" : "justify-between p-4"}`}>
                <div className="min-w-0" data-testid="sidebar-logo">
                    <div className="flex items-center gap-2">
                        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-[#0f2044] shadow-sm ring-1 ring-white/10">
                            <span className="text-white font-bold text-sm font-heading">K</span>
                        </div>
                        {!compact && <div>
                            <h2 className="font-heading text-sm font-semibold uppercase leading-none text-foreground">Kuryos</h2>
                            <p className="mt-0.5 text-[10px] uppercase leading-none text-muted-foreground">ERP</p>
                        </div>}
                    </div>
                    {!compact && <p className="mt-3 truncate rounded-lg bg-muted/55 px-2.5 py-2 text-xs text-muted-foreground">
                        {user?.name} <span className="opacity-60">· {user?.role}</span>
                    </p>}
                </div>
                {!compact && (
                    <button
                        type="button"
                        className="hidden rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground md:inline-flex"
                        onClick={() => setCollapsed(true)}
                        data-testid="sidebar-collapse-btn"
                        aria-label="Minimizar menu"
                        title="Minimizar menu"
                    >
                        <PanelLeftClose className="h-4 w-4" />
                    </button>
                )}
                {compact && (
                    <button
                        type="button"
                        className="absolute left-[52px] top-4 hidden rounded-lg border border-border/70 bg-card/95 p-1.5 text-muted-foreground shadow-sm backdrop-blur hover:bg-muted hover:text-foreground md:inline-flex"
                        onClick={() => setCollapsed(false)}
                        data-testid="sidebar-expand-btn"
                        aria-label="Expandir menu"
                        title="Expandir menu"
                    >
                        <PanelLeftOpen className="h-3.5 w-3.5" />
                    </button>
                )}
                <button
                    type="button"
                    className={`${compact ? "hidden" : "md:hidden"} rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground`}
                    onClick={() => setMobileOpen(false)}
                    data-testid="sidebar-close-mobile"
                    aria-label="Fechar menu"
                >
                    <X className="h-4 w-4" />
                </button>
            </div>

            <Separator />

            <nav ref={navRef} className={`flex-1 space-y-1 overflow-y-auto ${compact ? "p-2" : "px-3 py-2"}`} data-testid="sidebar-nav">
                {filteredModules.map((mod) => {
                    const Icon = mod.icon;
                    if (mod.type === "link") {
                        const active = isActive(mod.path);
                        return (
                            <button
                                key={mod.key}
                                onClick={() => handleNavigate(mod.path)}
                                data-testid={`nav-${mod.key}`}
                                title={compact ? mod.label : undefined}
                                className={`sidebar-item w-full flex items-center ${compact ? "justify-center px-0" : "gap-3 px-3"} py-2.5 text-sm ${
                                    active ? "active bg-accent text-foreground font-medium" : "text-muted-foreground hover:text-foreground"
                                }`}
                            >
                                <Icon className="h-4 w-4 shrink-0" />
                                {!compact && mod.label}
                            </button>
                        );
                    }

                    const isOpen = openGroups[mod.key];
                    const hasActiveChild = mod.basePaths.some(bp => location.pathname === bp || location.pathname.startsWith(bp + "/"));
                    return (
                        <div key={mod.key} className="space-y-0.5">
                            <button
                                onClick={() => toggleGroup(mod.key)}
                                data-testid={`nav-group-${mod.key}`}
                                title={compact ? mod.label : undefined}
                                className={`sidebar-item w-full flex items-center ${compact ? "justify-center px-0" : "gap-3 px-3"} py-2.5 text-sm ${
                                    hasActiveChild ? "text-foreground font-medium" : "text-muted-foreground hover:text-foreground"
                                }`}
                            >
                                <Icon className="h-4 w-4 shrink-0" />
                                {!compact && <span className="flex-1 text-left">{mod.label}</span>}
                                {!compact && (isOpen ? (
                                    <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                                ) : (
                                    <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                                ))}
                            </button>
                            {isOpen && !compact && (
                                <div className="ml-4 pl-3 border-l border-border/60 space-y-0.5">
                                    {mod.children.map((child) => {
                                        const childActive = isActive(child.path);
                                        const ChildIcon = child.icon;
                                        return (
                                            <button
                                                key={child.path}
                                                onClick={() => handleNavigate(child.path)}
                                                data-testid={`nav-${mod.key}-${child.path.split("/").pop()}`}
                                                className={`sidebar-item w-full flex items-center gap-2 px-3 py-2 text-xs ${
                                                    childActive ? "active bg-accent text-foreground font-medium" : "text-muted-foreground hover:text-foreground"
                                                }`}
                                            >
                                                {ChildIcon && <ChildIcon className="h-3.5 w-3.5 shrink-0" />}
                                                <span className="truncate">{child.label}</span>
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    );
                })}
            </nav>

            <div className={`${compact ? "p-2" : "p-3"} space-y-1`}>
                <Separator className="mb-2" />
                {!compact && <NotificationPanel />}
                <button
                    onClick={() => setDark(!dark)}
                    data-testid="theme-toggle"
                    title={compact ? (dark ? "Modo Claro" : "Modo Escuro") : undefined}
                    className={`sidebar-item w-full flex items-center ${compact ? "justify-center px-0" : "gap-3 px-3"} py-2.5 text-sm text-muted-foreground hover:text-foreground`}
                >
                    {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                    {!compact && (dark ? "Modo Claro" : "Modo Escuro")}
                </button>
                <button
                    onClick={logout}
                    data-testid="logout-btn"
                    title={compact ? "Sair" : undefined}
                    className={`sidebar-item w-full flex items-center ${compact ? "justify-center px-0" : "gap-3 px-3"} py-2.5 text-sm text-muted-foreground hover:text-foreground`}
                >
                    <LogOut className="h-4 w-4" />
                    {!compact && "Sair"}
                </button>
            </div>
        </>
    );

    return (
        <TooltipProvider delayDuration={200}>
            {/* Mobile top bar */}
            <div className="fixed left-0 right-0 top-0 z-40 flex h-14 items-center justify-between border-b border-border/70 bg-card/85 px-4 shadow-sm backdrop-blur-xl md:hidden" data-testid="mobile-topbar">
                <button
                    type="button"
                    onClick={() => setMobileOpen(true)}
                    data-testid="mobile-menu-btn"
                    aria-label="Abrir menu"
                    className="rounded-lg p-2 text-foreground hover:bg-muted"
                >
                    <Menu className="h-5 w-5" />
                </button>
                <div className="flex items-center gap-2">
                    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#0f2044] shadow-sm">
                        <span className="text-white font-bold text-xs">K</span>
                    </div>
                    <span className="font-heading text-sm font-semibold uppercase">Kuryos</span>
                </div>
                <div className="w-9" />
            </div>

            {/* Desktop sidebar */}
            <aside
                className={`${collapsed ? "w-[72px]" : "w-[260px]"} relative hidden h-screen shrink-0 flex-col border-r border-border/70 bg-card/82 shadow-sm backdrop-blur-xl transition-[width] duration-200 md:flex`}
                data-testid="sidebar"
            >
                {sidebarContent({ compact: collapsed })}
            </aside>

            {/* Mobile drawer */}
            {mobileOpen && (
                <div className="md:hidden fixed inset-0 z-50 flex" data-testid="mobile-sidebar-drawer">
                    <div
                        className="absolute inset-0 bg-black/45 backdrop-blur-sm"
                        onClick={() => setMobileOpen(false)}
                        aria-hidden="true"
                    />
                    <aside className="relative flex h-screen w-[min(86vw,300px)] flex-col border-r border-border/70 bg-card/95 shadow-2xl backdrop-blur-xl">
                        {sidebarContent({ compact: false })}
                    </aside>
                </div>
            )}
        </TooltipProvider>
    );
}
