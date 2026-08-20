import { useState, useEffect } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
    ClipboardList, CheckSquare, AlertTriangle, FlaskConical,
    ChevronRight, Loader2, RefreshCw, RotateCcw,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

export default function CQDashboard() {
    const navigate = useNavigate();
    const { user } = useAuth();
    const [loading, setLoading] = useState(true);
    const [cards, setCards] = useState({ rasPendentes: 0, checklistsAtivos: 0, rncsAbertas: 0, instrumentosVencidos: 0, retrabalhoAtivos: 0 });
    const [tasks, setTasks] = useState([]);
    const [tasksLoading, setTasksLoading] = useState(true);

    const loadCards = async () => {
        setLoading(true);
        try {
            const [rasDraftRes, rasAnalysisRes, ckRes, rncRes, instrRes, rtRes] = await Promise.all([
                api.get("/cq/registros-analise", { params: { status: "rascunho" } }),
                api.get("/cq/registros-analise", { params: { status: "em_analise" } }),
                api.get("/cq/checklists", { params: { status: "em_preenchimento" } }),
                api.get("/cq/rncs", { params: { status: "aberta" } }),
                api.get("/cq/instrumentos"),
                api.get("/retrabalho/dashboard").catch(() => ({ data: { total_ativos: 0 } })),
            ]);
            const countResponse = (res) => Array.isArray(res.data)
                ? res.data.length
                : (res.data?.total ?? res.data?.count ?? 0);
            const rasPendentes = countResponse(rasDraftRes) + countResponse(rasAnalysisRes);
            const checklistsAtivos = Array.isArray(ckRes.data)
                ? ckRes.data.length
                : (ckRes.data?.total ?? ckRes.data?.count ?? 0);
            const rncsAbertas = Array.isArray(rncRes.data)
                ? rncRes.data.length
                : (rncRes.data?.total ?? rncRes.data?.count ?? 0);
            const instrList = Array.isArray(instrRes.data)
                ? instrRes.data
                : (instrRes.data?.items ?? instrRes.data?.data ?? []);
            const instrumentosVencidos = instrList.filter(i => i.status === "vencido").length;
            const retrabalhoAtivos = rtRes.data?.total_ativos ?? 0;
            setCards({ rasPendentes, checklistsAtivos, rncsAbertas, instrumentosVencidos, retrabalhoAtivos });
        } catch (e) {
            toast.error("Erro ao carregar dados do dashboard CQ");
        } finally {
            setLoading(false);
        }
    };

    const loadTasks = async () => {
        setTasksLoading(true);
        try {
            const { data } = await api.get("/workflow/tasks", { params: { status: "pendente", q: "CQ-" } });
            const list = Array.isArray(data) ? data : (data?.items ?? data?.tasks ?? []);
            setTasks(list.filter(t => t.title && t.title.startsWith("CQ-")));
        } catch (e) {
            // silently fail tasks
        } finally {
            setTasksLoading(false);
        }
    };

    useEffect(() => {
        loadCards();
        loadTasks();
    }, []);

    const cardDefs = [
        {
            testId: "card-ras-pendentes",
            label: "RAs Pendentes",
            value: cards.rasPendentes,
            icon: ClipboardList,
            color: "text-blue-600",
            bg: "bg-blue-50 dark:bg-blue-950/30",
            border: "border-blue-200 dark:border-blue-800",
        },
        {
            testId: "card-checklists-ativos",
            label: "Checklists Ativos",
            value: cards.checklistsAtivos,
            icon: CheckSquare,
            color: "text-amber-600",
            bg: "bg-amber-50 dark:bg-amber-950/30",
            border: "border-amber-200 dark:border-amber-800",
        },
        {
            testId: "card-rncs-abertas",
            label: "RNCs Abertas",
            value: cards.rncsAbertas,
            icon: AlertTriangle,
            color: "text-red-600",
            bg: "bg-red-50 dark:bg-red-950/30",
            border: "border-red-200 dark:border-red-800",
        },
        {
            testId: "card-instrumentos-vencidos",
            label: "Instrumentos Vencidos",
            value: cards.instrumentosVencidos,
            icon: FlaskConical,
            color: "text-red-600",
            bg: "bg-red-50 dark:bg-red-950/30",
            border: "border-red-200 dark:border-red-800",
        },
        {
            testId: "card-retrabalho-ativos",
            label: "Retrabalhos Ativos",
            value: cards.retrabalhoAtivos,
            icon: RotateCcw,
            color: "text-orange-600",
            bg: "bg-orange-50 dark:bg-orange-950/30",
            border: "border-orange-200 dark:border-orange-800",
        },
    ];

    const navButtons = [
        { label: "Registros de Análise", path: "/cq/registros-analise", icon: ClipboardList },
        { label: "Checklists", path: "/cq/checklists", icon: CheckSquare },
        { label: "RNCs", path: "/cq/rncs", icon: AlertTriangle },
        { label: "Retenções", path: "/cq/retencoes", icon: FlaskConical },
        { label: "Instrumentos", path: "/cq/instrumentos", icon: FlaskConical },
        { label: "Retrabalho", path: "/cq/retrabalho", icon: RotateCcw },
    ];

    return (
        <div className="p-6 page-enter" data-testid="cq-dashboard">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-3xl font-heading font-semibold tracking-tight">Controle de Qualidade</h1>
                    <p className="text-sm text-muted-foreground mt-1">Visão geral do módulo CQ</p>
                </div>
                <Button variant="outline" size="sm" onClick={() => { loadCards(); loadTasks(); }}>
                    <RefreshCw className="h-4 w-4 mr-2" /> Atualizar
                </Button>
            </div>

            {/* Summary Cards */}
            {loading ? (
                <div className="flex items-center justify-center h-40">
                    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
                    {cardDefs.map((card) => {
                        const Icon = card.icon;
                        return (
                            <div
                                key={card.testId}
                                data-testid={card.testId}
                                className={`rounded-xl border p-5 ${card.bg} ${card.border}`}
                            >
                                <div className="flex items-center justify-between mb-3">
                                    <p className="text-sm font-medium text-foreground">{card.label}</p>
                                    <Icon className={`h-5 w-5 ${card.color}`} />
                                </div>
                                <p className={`text-3xl font-bold ${card.color}`}>{card.value}</p>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Pending Tasks */}
            <div className="mb-8">
                <h2 className="text-lg font-heading font-semibold mb-3">Tarefas CQ Pendentes</h2>
                {tasksLoading ? (
                    <div className="flex items-center gap-2 text-muted-foreground text-sm">
                        <Loader2 className="h-4 w-4 animate-spin" /> Carregando tarefas...
                    </div>
                ) : tasks.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Nenhuma tarefa CQ pendente.</p>
                ) : (
                    <div className="space-y-2">
                        {tasks.map((task) => (
                            <div
                                key={task.id}
                                className="flex items-center justify-between rounded-lg border border-border bg-card p-3 cursor-pointer hover:bg-accent/50 transition-colors"
                                onClick={() => navigate("/tasks")}
                                data-testid={`task-row-${task.id}`}
                            >
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium truncate">{task.title}</p>
                                    {task.responsible_name && (
                                        <p className="text-xs text-muted-foreground">Responsável: {task.responsible_name}</p>
                                    )}
                                </div>
                                <div className="flex items-center gap-3 ml-3">
                                    {task.due_date && (
                                        <span className="text-xs text-muted-foreground mono-num">
                                            {new Date(task.due_date).toLocaleDateString("pt-BR")}
                                        </span>
                                    )}
                                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Navigation Buttons */}
            <div>
                <h2 className="text-lg font-heading font-semibold mb-3">Módulos</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {navButtons.map((btn) => {
                        const Icon = btn.icon;
                        return (
                            <Button
                                key={btn.path}
                                variant="outline"
                                className="justify-between h-12"
                                onClick={() => navigate(btn.path)}
                                data-testid={`nav-${btn.path.replace(/\//g, "-").slice(1)}`}
                            >
                                <div className="flex items-center gap-2">
                                    <Icon className="h-4 w-4" />
                                    <span>{btn.label}</span>
                                </div>
                                <ChevronRight className="h-4 w-4 text-muted-foreground" />
                            </Button>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
