import { createContext, lazy, Suspense, useContext, useEffect, useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import LoginPage from "@/pages/LoginPage";
import Sidebar from "@/components/Sidebar";
import RoleGuard, { ROLE_GROUPS } from "@/components/RoleGuard";
import { Toaster } from "@/components/ui/sonner";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const PipelinePage = lazy(() => import("@/pages/PipelinePage"));
const TeamPage = lazy(() => import("@/pages/TeamPage"));
const PDPage = lazy(() => import("@/pages/PDPage"));
const PDDetail = lazy(() => import("@/pages/PDDetail"));
const PDCatalog = lazy(() => import("@/pages/PDCatalog"));
const PDStock = lazy(() => import("@/pages/PDStock"));
const PDFormulaBank = lazy(() => import("@/pages/PDFormulaBank"));
const PDHomologacao = lazy(() => import("@/pages/PDHomologacao"));
const PDReports = lazy(() => import("@/pages/PDReports"));
const CRM1Page = lazy(() => import("@/pages/CRM1Page"));
const CRM2Page = lazy(() => import("@/pages/CRM2Page"));
const CRM3Page = lazy(() => import("@/pages/CRM3Page"));
const CommercialBudgetPage = lazy(() => import("@/pages/CommercialBudgetPage"));
const KickoffPage = lazy(() => import("@/pages/KickoffPage"));
const KickoffsListPage = lazy(() => import("@/pages/KickoffsListPage"));
const SKUsPage = lazy(() => import("@/pages/SKUsPage"));
const TasksPage = lazy(() => import("@/pages/TasksPage"));
const AuditLogPage = lazy(() => import("@/pages/AuditLogPage"));
const CQDashboard = lazy(() => import("@/pages/CQDashboard"));
const CQListaRA = lazy(() => import("@/pages/CQListaRA"));
const CQDetalheRA = lazy(() => import("@/pages/CQDetalheRA"));
const CQListaChecklists = lazy(() => import("@/pages/CQListaChecklists"));
const CQPreencherChecklist = lazy(() => import("@/pages/CQPreencherChecklist"));
const CQListaRNCs = lazy(() => import("@/pages/CQListaRNCs"));
const CQDetalheRNC = lazy(() => import("@/pages/CQDetalheRNC"));
const CQRetencoes = lazy(() => import("@/pages/CQRetencoes"));
const CQDetalheRetencao = lazy(() => import("@/pages/CQDetalheRetencao"));
const CQInstrumentos = lazy(() => import("@/pages/CQInstrumentos"));
const CQRetrabalho = lazy(() => import("@/pages/CQRetrabalho"));
const OrdersPage = lazy(() => import("@/pages/OrdersPage"));
const OrderDetail = lazy(() => import("@/pages/OrderDetail"));
const OrderGeneratorPage = lazy(() => import("@/pages/OrderGeneratorPage"));
const OPPage = lazy(() => import("@/pages/OPPage"));
const OPDetail = lazy(() => import("@/pages/OPDetail"));
const ComprasDashboard = lazy(() => import("@/pages/ComprasDashboard"));
const ComprasFornecedores = lazy(() => import("@/pages/ComprasFornecedores"));
const ComprasFornecedorDetalhe = lazy(() => import("@/pages/ComprasFornecedorDetalhe"));
const ComprasItens = lazy(() => import("@/pages/ComprasItens"));
const ComprasItemDetalhe = lazy(() => import("@/pages/ComprasItemDetalhe"));
const ComprasMRP = lazy(() => import("@/pages/ComprasMRP"));
const ComprasMRPRevisao = lazy(() => import("@/pages/ComprasMRPRevisao"));
const ComprasCotacao = lazy(() => import("@/pages/ComprasCotacao"));
const ComprasPOLista = lazy(() => import("@/pages/ComprasPOLista"));
const ComprasPODetalhe = lazy(() => import("@/pages/ComprasPODetalhe"));
const ComprasEstoqueProjetado = lazy(() => import("@/pages/ComprasEstoqueProjetado"));
const EstoquePage = lazy(() => import("@/pages/EstoquePage"));
const MovimentacaoPage = lazy(() => import("@/pages/MovimentacaoPage"));
const RecebimentoPage = lazy(() => import("@/pages/RecebimentoPage"));
const ExpedicaoPage = lazy(() => import("@/pages/ExpedicaoPage"));
const FaturamentoPage = lazy(() => import("@/pages/FaturamentoPage"));
const LogisticaPage = lazy(() => import("@/pages/LogisticaPage"));
const PCPDailyDashboard = lazy(() => import("@/pages/PCPDailyDashboard"));
const PCPClonePage = lazy(() => import("@/pages/PCPClonePage"));
const PCPProductionPage = lazy(() => import("@/pages/PCPProductionPage"));
const ContratosPage = lazy(() => import("@/pages/ContratosPage"));
const CadastrosPage = lazy(() => import("@/pages/CadastrosPage"));

function ThemeProvider({ children }) {
    const [dark, setDark] = useState(() => localStorage.getItem("theme") !== "light");

    useEffect(() => {
        document.documentElement.classList.toggle("dark", dark);
        localStorage.setItem("theme", dark ? "dark" : "light");
    }, [dark]);

    return (
        <ThemeCtx.Provider value={{ dark, setDark }}>
            {children}
        </ThemeCtx.Provider>
    );
}

const ThemeCtx = createContext({ dark: false, setDark: () => {} });
export const useTheme = () => useContext(ThemeCtx);

function PageLoader() {
    return (
        <div className="flex min-h-[240px] items-center justify-center" data-testid="page-loader">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
    );
}

function ProtectedRoute({ children }) {
    const { user, loading } = useAuth();
    if (loading) return (
        <div className="h-screen flex items-center justify-center bg-background" data-testid="loading-screen">
            <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
        </div>
    );
    if (!user) return <Navigate to="/login" replace />;
    return children;
}

function AppLayout() {
    const COMERCIAL = ROLE_GROUPS.COMERCIAL_FULL;
    const PD_READ = ROLE_GROUPS.PD_READ;
    const PD_FULL = ROLE_GROUPS.PD_FULL;
    const ADMIN_ONLY = ROLE_GROUPS.ADMIN_ONLY;
    const AUDIT_ROLES = [...ROLE_GROUPS.DOC_REVIEWERS, "sales_ops"];
    const KICKOFF_ROLES = [...new Set([...COMERCIAL, ...PD_FULL])];
    const CQ_ROLES = ["admin", "qa", "lider_pd", "formulador", "engenharia_produto", "compras", "sales_ops"];
    const COMPRAS_ROLES = ["admin", "compras", "engenharia_produto", "lider_pd", "qa", "sales_ops"];
    const CONTRATOS_ROLES = ["admin", "sales_ops", "vendedor", "compras", "lider_pd", "qa", "engenharia_produto", "sucesso_cliente"];
    const CADASTROS_ROLES = ["admin", "vendedor", "sales_ops", "sucesso_cliente", "lider_pd", "formulador", "qa", "engenharia_produto", "compras", "gestor"];

    return (
        <div className="flex min-h-screen md:h-screen overflow-hidden bg-background">
            <Sidebar />
            <main className="flex-1 overflow-auto pt-14 md:pt-0">
                <Suspense fallback={<PageLoader />}>
                    <Routes>
                        <Route path="/" element={<Navigate to="/tasks" replace />} />
                        <Route path="/dashboard" element={<DashboardPage />} />
                        <Route path="/pipeline" element={<RoleGuard allowed={COMERCIAL}><PipelinePage /></RoleGuard>} />
                        <Route path="/crm/clients" element={<RoleGuard allowed={COMERCIAL}><CRM1Page /></RoleGuard>} />
                        <Route path="/crm/projects" element={<RoleGuard allowed={COMERCIAL}><CRM2Page /></RoleGuard>} />
                        <Route path="/crm/samples" element={<RoleGuard allowed={COMERCIAL}><CRM3Page /></RoleGuard>} />
                        <Route path="/crm/orcamentos" element={<RoleGuard allowed={COMERCIAL}><CommercialBudgetPage /></RoleGuard>} />
                        <Route path="/kickoffs" element={<RoleGuard allowed={KICKOFF_ROLES}><KickoffsListPage /></RoleGuard>} />
                        <Route path="/kickoff/:id" element={<RoleGuard allowed={KICKOFF_ROLES}><KickoffPage /></RoleGuard>} />
                        <Route path="/crm/skus" element={<RoleGuard allowed={[...PD_READ, ...COMERCIAL]}><SKUsPage /></RoleGuard>} />
                        <Route path="/pd" element={<RoleGuard allowed={PD_READ}><PDPage /></RoleGuard>} />
                        <Route path="/pd/formulas" element={<RoleGuard allowed={PD_READ}><PDFormulaBank /></RoleGuard>} />
                        <Route path="/pd/homologacao" element={<RoleGuard allowed={PD_FULL}><PDHomologacao /></RoleGuard>} />
                        <Route path="/homologacoes" element={<RoleGuard allowed={PD_FULL}><PDHomologacao /></RoleGuard>} />
                        <Route path="/pd/catalog" element={<RoleGuard allowed={PD_FULL}><PDCatalog /></RoleGuard>} />
                        <Route path="/pd/estoque" element={<RoleGuard allowed={PD_FULL}><PDStock /></RoleGuard>} />
                        <Route path="/pd/relatorios" element={<RoleGuard allowed={PD_READ}><PDReports /></RoleGuard>} />
                        <Route path="/pd/:id" element={<RoleGuard allowed={[...PD_READ, ...COMERCIAL]}><PDDetail /></RoleGuard>} />
                        <Route path="/tasks" element={<TasksPage />} />
                        <Route path="/orders" element={<OrdersPage />} />
                        <Route path="/orders/gerador" element={<OrderGeneratorPage />} />
                        <Route path="/orders/:id" element={<OrderDetail />} />
                        <Route path="/ops" element={<OPPage />} />
                        <Route path="/ops/:id" element={<OPDetail />} />
                        <Route path="/pcp/dashboard" element={<PCPDailyDashboard />} />
                        <Route path="/pcp/planejamento" element={<PCPClonePage mode="planejamento" />} />
                        <Route path="/pcp/horizonte" element={<PCPClonePage mode="horizonte" />} />
                        <Route path="/pcp/controle-ops" element={<PCPClonePage mode="controle" />} />
                        <Route path="/pcp/produtos" element={<Navigate to="/cadastros" replace />} />
                        <Route path="/pcp/insumos" element={<Navigate to="/cadastros" replace />} />
                        <Route path="/pcp/apontamento" element={<Navigate to="/pcp/apontamento/envase" replace />} />
                        <Route path="/pcp/apontamento/:setor" element={<PCPProductionPage />} />
                        <Route path="/pcp" element={<Navigate to="/pcp/dashboard" replace />} />
                        <Route path="/cadastros" element={<RoleGuard allowed={CADASTROS_ROLES}><CadastrosPage /></RoleGuard>} />
                        <Route path="/logistica" element={<LogisticaPage />} />
                        <Route path="/expedicao" element={<ExpedicaoPage />} />
                        <Route path="/faturamento" element={<FaturamentoPage />} />
                        <Route path="/compras" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasDashboard /></RoleGuard>} />
                        <Route path="/compras/fornecedores" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasFornecedores /></RoleGuard>} />
                        <Route path="/compras/fornecedores/:id" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasFornecedorDetalhe /></RoleGuard>} />
                        <Route path="/compras/itens" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasItens /></RoleGuard>} />
                        <Route path="/compras/itens/:id" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasItemDetalhe /></RoleGuard>} />
                        <Route path="/compras/mrp" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasMRP /></RoleGuard>} />
                        <Route path="/compras/mrp/:id" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasMRPRevisao /></RoleGuard>} />
                        <Route path="/compras/cotacao/:demanda_id" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasCotacao /></RoleGuard>} />
                        <Route path="/compras/pos" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasPOLista /></RoleGuard>} />
                        <Route path="/compras/pos/:id" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasPODetalhe /></RoleGuard>} />
                        <Route path="/compras/estoque-projetado" element={<RoleGuard allowed={COMPRAS_ROLES}><ComprasEstoqueProjetado /></RoleGuard>} />
                        <Route path="/estoque" element={<EstoquePage />} />
                        <Route path="/estoque/movimentacao" element={<MovimentacaoPage />} />
                        <Route path="/recebimento" element={<RecebimentoPage />} />
                        <Route path="/contratos" element={<RoleGuard allowed={CONTRATOS_ROLES}><ContratosPage /></RoleGuard>} />
                        <Route path="/audit" element={<RoleGuard allowed={AUDIT_ROLES}><AuditLogPage /></RoleGuard>} />
                        <Route path="/cq" element={<RoleGuard allowed={CQ_ROLES}><CQDashboard /></RoleGuard>} />
                        <Route path="/cq/registros-analise" element={<RoleGuard allowed={CQ_ROLES}><CQListaRA /></RoleGuard>} />
                        <Route path="/cq/registros-analise/:id" element={<RoleGuard allowed={CQ_ROLES}><CQDetalheRA /></RoleGuard>} />
                        <Route path="/cq/checklists" element={<RoleGuard allowed={CQ_ROLES}><CQListaChecklists /></RoleGuard>} />
                        <Route path="/cq/checklists/:id" element={<RoleGuard allowed={CQ_ROLES}><CQPreencherChecklist /></RoleGuard>} />
                        <Route path="/cq/rncs" element={<RoleGuard allowed={CQ_ROLES}><CQListaRNCs /></RoleGuard>} />
                        <Route path="/cq/rncs/:id" element={<RoleGuard allowed={CQ_ROLES}><CQDetalheRNC /></RoleGuard>} />
                        <Route path="/cq/retencoes" element={<RoleGuard allowed={CQ_ROLES}><CQRetencoes /></RoleGuard>} />
                        <Route path="/cq/retencoes/:id" element={<RoleGuard allowed={CQ_ROLES}><CQDetalheRetencao /></RoleGuard>} />
                        <Route path="/cq/instrumentos" element={<RoleGuard allowed={CQ_ROLES}><CQInstrumentos /></RoleGuard>} />
                        <Route path="/cq/retrabalho" element={<RoleGuard allowed={CQ_ROLES}><CQRetrabalho /></RoleGuard>} />
                        <Route path="/team" element={<RoleGuard allowed={ADMIN_ONLY}><TeamPage /></RoleGuard>} />
                    </Routes>
                </Suspense>
            </main>
        </div>
    );
}

function App() {
    return (
        <ThemeProvider>
            <AuthProvider>
                <BrowserRouter>
                    <Suspense fallback={<PageLoader />}>
                        <Routes>
                            <Route path="/login" element={<LoginPage />} />
                            <Route path="/*" element={
                                <ProtectedRoute>
                                    <AppLayout />
                                </ProtectedRoute>
                            } />
                        </Routes>
                    </Suspense>
                </BrowserRouter>
                <Toaster position="top-right" />
            </AuthProvider>
        </ThemeProvider>
    );
}

export default App;
