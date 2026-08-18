import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Calendar,
  AlertTriangle,
  Filter,
  CheckCircle2,
  Clock,
  User,
  Tag,
  Layers,
  ShieldCheck,
  ShieldX,
  Plus,
  Bell,
  TrendingUp,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { formatApiError } from "@/lib/formatError";

const STATUS_VARIANT = {
  pendente: { label: "Pendente", variant: "secondary", icon: Clock },
  em_andamento: { label: "Em Andamento", variant: "default", icon: Clock },
  concluida: { label: "Concluida", variant: "outline", icon: CheckCircle2 },
  cancelada: { label: "Cancelada", variant: "destructive", icon: AlertTriangle },
};

const DECISION_LABEL = {
  approved: "Aprovada",
  rejected: "Reprovada",
};

const ENTITY_LABEL = {
  client: "Cliente",
  project: "Projeto",
  sample: "Amostra",
  variacao: "Variacao",
  pd_card: "Card P&D",
  stability_study: "Estabilidade",
  sku: "SKU",
};

const CATEGORY_LABEL = {
  qualificacao: "Qualificacao",
  projeto: "Projeto",
  amostra: "Amostra",
  pd_dev: "Desenvolvimento",
  qa: "Controle de Qualidade",
  cliente_feedback: "Feedback Cliente",
  fechamento: "Fechamento",
  comercial: "Comercial",
  manual: "Manual",
};

const VIEW_LABELS = {
  mine: "Minhas Tarefas",
  overdue: "Em Atraso",
  week: "Esta Semana",
  blocking: "Bloqueantes",
  done: "Concluidas",
  all: "Visao Global",
};

export default function TasksPage() {
  const { user } = useAuth();
  const isLeader = ["admin", "gestor", "lider_pd", "sales_ops"].includes(user?.role);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState("mine");
  const [entityFilter, setEntityFilter] = useState("all");
  const [actionOpen, setActionOpen] = useState(false);
  const [activeTask, setActiveTask] = useState(null);
  const [actionMode, setActionMode] = useState("complete");
  const [comment, setComment] = useState("");
  const [allOpenTasks, setAllOpenTasks] = useState([]);
  const [showCreateTask, setShowCreateTask] = useState(false);
  const [createForm, setCreateForm] = useState({ title: "", description: "", entity_type: "pd_card", entity_id: "", due_in_days: 3, blocking: false, priority: "normal" });
  const [creatingTask, setCreatingTask] = useState(false);
  const [checkingReminders, setCheckingReminders] = useState(false);
  const [runningStability, setRunningStability] = useState(false);
  const [stabilityStatus, setStabilityStatus] = useState(null);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/workflow/tasks", { params: getParamsForView(viewMode, isLeader) });
      setTasks(data || []);
    } catch (error) {
      toast.error(formatApiError(error));
    } finally {
      setLoading(false);
    }
  }, [viewMode, isLeader]);

  const loadStabilityStatus = useCallback(async () => {
    try {
      const { data } = await api.get("/pd/stability/scheduler-status");
      setStabilityStatus(data);
    } catch { setStabilityStatus(null); }
  }, []);

  const checkReminders = async () => {
    setCheckingReminders(true);
    try {
      const { data } = await api.post("/workflow/tasks/check-reminders");
      toast.success(`Lembretes: ${data.d1_notified} D-1 enviados · ${data.escalated} escalados`);
      loadTasks();
    } catch { toast.error("Erro ao verificar lembretes"); }
    finally { setCheckingReminders(false); }
  };

  const runStabilityScan = async () => {
    setRunningStability(true);
    try {
      const { data } = await api.post("/pd/stability/run-scheduler");
      toast.success(`Scan D-2 rodado: ${data.alerts_created} alerta(s) criado(s)`);
      loadStabilityStatus();
      loadTasks();
    } catch (err) {
      toast.error(formatApiError(err));
    } finally { setRunningStability(false); }
  };

  useEffect(() => { loadStabilityStatus(); }, [loadStabilityStatus]);

  const submitCreateTask = async () => {
    if (!createForm.title.trim()) return toast.error("Título obrigatório");
    if (!createForm.entity_id.trim()) return toast.error("ID da entidade obrigatório");
    setCreatingTask(true);
    try {
      await api.post("/workflow/tasks", { ...createForm, due_in_days: Number(createForm.due_in_days) || 3 });
      toast.success("Tarefa criada!");
      setShowCreateTask(false);
      setCreateForm({ title: "", description: "", entity_type: "pd_card", entity_id: "", due_in_days: 3, blocking: false, priority: "normal" });
      loadTasks();
    } catch (err) { toast.error(formatApiError(err)); }
    finally { setCreatingTask(false); }
  };

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    // Always fetch the user's open tasks for the KPI summary, regardless of viewMode
    api
      .get("/workflow/tasks", { params: { mine: true } })
      .then(({ data }) => setAllOpenTasks(data || []))
      .catch(() => setAllOpenTasks([]));
  }, []);

  const filtered = useMemo(() => {
    return tasks.filter((task) => {
      if (entityFilter !== "all" && task.entity_type !== entityFilter) return false;
      if (viewMode === "mine" && task.status === "concluida") return false;
      if (viewMode === "blocking" && task.status === "concluida") return false;
      return true;
    });
  }, [tasks, entityFilter, viewMode]);

  const totalsByEntity = useMemo(() => {
    const map = {};
    tasks.forEach((task) => {
      if (task.status === "concluida") return;
      map[task.entity_type] = (map[task.entity_type] || 0) + 1;
    });
    return map;
  }, [tasks]);

  const blockingCount = tasks.filter((task) => task.blocking && task.status !== "concluida").length;

  // KPI counts based on the user's open tasks (always loaded, independent of view filter)
  const kpiCounts = useMemo(() => {
    const now = Date.now();
    const open = allOpenTasks.filter((t) => t.status !== "concluida");
    const overdue = open.filter((t) => t.due_date && new Date(t.due_date).getTime() < now);
    const week = open.filter((t) => {
      if (!t.due_date) return false;
      const diff = new Date(t.due_date).getTime() - now;
      return diff >= 0 && diff <= 7 * 24 * 3600 * 1000;
    });
    const blocking = open.filter((t) => t.blocking);
    return { mine: open.length, overdue: overdue.length, week: week.length, blocking: blocking.length };
  }, [allOpenTasks]);

  const openActionDialog = (task, mode) => {
    setActiveTask(task);
    setActionMode(mode);
    setComment("");
    setActionOpen(true);
  };

  const submitAction = async () => {
    if (!activeTask) return;
    if (actionMode === "reject" && !comment.trim()) {
      toast.error("Justificativa obrigatoria para reprovar.");
      return;
    }

    try {
      if (actionMode === "complete") {
        await api.put(`/workflow/tasks/${activeTask.id}/complete`, { comment });
        toast.success("Tarefa concluida");
      } else {
        await api.put(`/workflow/tasks/${activeTask.id}/decision`, {
          decision: actionMode === "approve" ? "approved" : "rejected",
          comment,
        });
        toast.success(actionMode === "approve" ? "Aprovacao registrada" : "Reprovacao registrada");
      }
      setActionOpen(false);
      setActiveTask(null);
      setComment("");
      loadTasks();
    } catch (error) {
      toast.error(formatApiError(error));
    }
  };

  if (loading) {
    return (
      <div className="p-4 sm:p-6 lg:p-8" data-testid="tasks-loading">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-40 rounded bg-muted" />
          {[1, 2, 3].map((item) => (
            <div key={item} className="h-20 rounded-lg bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 page-enter" data-testid="tasks-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl sm:text-3xl font-heading font-semibold tracking-tight">Tarefas</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Painel inicial de <span className="font-medium text-foreground">{user?.role}</span> · {VIEW_LABELS[viewMode]}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {blockingCount > 0 && (
            <Badge variant="destructive" className="text-xs px-3 py-1.5" data-testid="blocking-count">
              <AlertTriangle className="h-3 w-3 mr-1" />
              {blockingCount} bloqueante(s)
            </Badge>
          )}
          {isLeader && <Badge variant="outline">Visao global habilitada</Badge>}
          <Button size="sm" variant="outline" className="gap-1.5" onClick={checkReminders} disabled={checkingReminders} data-testid="check-reminders-btn">
            {checkingReminders ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Bell className="h-3.5 w-3.5" />}
            Verificar D-1
          </Button>
          {(user?.role === "admin" || user?.role === "lider_pd" || user?.role === "qa" || user?.role === "formulador") && (
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={runStabilityScan}
              disabled={runningStability}
              data-testid="run-stability-scan-btn"
              title={
                stabilityStatus?.last_run_at
                  ? `Scheduler ativo · última execução: ${stabilityStatus.last_run_at?.replace("T", " ").slice(0, 16)}`
                  : "Scheduler ativo · nenhuma execução registrada ainda"
              }
            >
              {runningStability ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
              Rodar scan D-2
            </Button>
          )}
          <Button size="sm" className="gap-1.5" onClick={() => setShowCreateTask(true)} data-testid="create-task-btn">
            <Plus className="h-3.5 w-3.5" /> Criar Tarefa
          </Button>
          <Badge variant="outline" data-testid="total-count">
            {tasks.length} itens
          </Badge>
        </div>
      </div>

      {/* KPI cards — Minhas / Em Atraso / Esta Semana / Bloqueantes */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="task-kpis">
        {[
          { key: "mine", label: "Minha Fila", value: kpiCounts.mine, icon: Clock, color: "text-primary" },
          { key: "overdue", label: "Em Atraso", value: kpiCounts.overdue, icon: AlertTriangle, color: "text-red-500" },
          { key: "week", label: "Esta Semana", value: kpiCounts.week, icon: Calendar, color: "text-amber-500" },
          { key: "blocking", label: "Bloqueantes", value: kpiCounts.blocking, icon: ShieldX, color: "text-fuchsia-500" },
        ].map((card) => {
          const ICon = card.icon;
          const active = viewMode === card.key;
          return (
            <button
              key={card.key}
              onClick={() => setViewMode(card.key)}
              data-testid={`kpi-${card.key}`}
              className={`text-left rounded-lg border p-4 transition-colors ${active ? "bg-accent border-primary" : "bg-card border-border hover:bg-accent"}`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">{card.label}</span>
                <ICon className={`h-4 w-4 ${card.color}`} />
              </div>
              <p className="text-2xl font-heading font-semibold mono-num mt-2">{card.value}</p>
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-3" data-testid="task-filters">
        <div className="flex gap-2 flex-wrap">
          {[
            { value: "mine", label: "Minhas" },
            { value: "overdue", label: "Em Atraso" },
            { value: "week", label: "Esta Semana" },
            { value: "blocking", label: "Bloqueantes" },
            { value: "done", label: "Concluidas" },
            { value: "all", label: isLeader ? "Global" : "Todas" },
          ].map((item) => (
            <Button
              key={item.value}
              size="sm"
              variant={viewMode === item.value ? "default" : "outline"}
              onClick={() => setViewMode(item.value)}
              data-testid={`filter-${item.value}`}
            >
              {item.label}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <Select value={entityFilter} onValueChange={setEntityFilter}>
            <SelectTrigger className="w-44 sm:w-52" data-testid="entity-filter">
              <SelectValue placeholder="Tipo de entidade" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas as entidades</SelectItem>
              {Object.entries(ENTITY_LABEL).map(([key, label]) => (
                <SelectItem key={key} value={key}>
                  {label} {totalsByEntity[key] ? `(${totalsByEntity[key]})` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-2">
        {filtered.length === 0 && (
          <Card>
            <CardContent className="p-10 text-center text-sm text-muted-foreground">
              Nenhuma tarefa encontrada para os filtros atuais.
            </CardContent>
          </Card>
        )}

        {filtered.map((task) => {
          const StatusIcon = STATUS_VARIANT[task.status]?.icon || Clock;
          return (
            <Card
              key={task.id}
              className={task.blocking && task.status !== "concluida" ? "border-l-4 border-l-destructive" : ""}
              data-testid={`task-${task.id}`}
            >
              <CardContent className="p-4 flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div>
                      <p className={`text-sm font-medium ${task.status === "concluida" ? "line-through text-muted-foreground" : ""}`}>
                        {task.title}
                      </p>
                      {task.description && <p className="text-xs text-muted-foreground mt-1">{task.description}</p>}
                    </div>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {task.escalated && task.status !== "concluida" && (
                        <Badge className="text-[10px] bg-red-600 text-white gap-1">
                          <TrendingUp className="h-2.5 w-2.5" /> Escalado
                        </Badge>
                      )}
                      {task.d1_notified && task.status !== "concluida" && !task.escalated && (
                        <Badge className="text-[10px] bg-amber-500/20 text-amber-700 border-amber-300 gap-1">
                          <Bell className="h-2.5 w-2.5" /> D-1
                        </Badge>
                      )}
                      {task.blocking && task.status !== "concluida" && (
                        <Badge variant="destructive" className="text-[10px] uppercase tracking-wider">
                          Bloqueante
                        </Badge>
                      )}
                      {task.task_type === "approval" && (
                        <Badge variant="outline" className="text-[10px] uppercase tracking-wider">
                          Aprovacao
                        </Badge>
                      )}
                      {task.decision && (
                        <Badge variant={task.decision === "approved" ? "default" : "destructive"}>
                          {DECISION_LABEL[task.decision]}
                        </Badge>
                      )}
                      <Badge variant={STATUS_VARIANT[task.status]?.variant || "secondary"} className="gap-1">
                        <StatusIcon className="h-3 w-3" />
                        {STATUS_VARIANT[task.status]?.label || task.status}
                      </Badge>
                    </div>
                  </div>

                  <div className="flex items-center flex-wrap gap-3 mt-3 text-xs">
                    <span className="flex items-center gap-1 text-muted-foreground">
                      <Layers className="h-3 w-3" />
                      {ENTITY_LABEL[task.entity_type] || task.entity_type}
                    </span>
                    {task.category && (
                      <span className="flex items-center gap-1 text-muted-foreground">
                        <Tag className="h-3 w-3" />
                        {CATEGORY_LABEL[task.category] || task.category}
                      </span>
                    )}
                    {task.responsible_name && (
                      <span className="flex items-center gap-1 text-muted-foreground">
                        <User className="h-3 w-3" />
                        {task.responsible_name}
                      </span>
                    )}
                    {task.due_date && (
                      <span className={`flex items-center gap-1 ${getDueClass(task.due_date, task.status)}`}>
                        <Calendar className="h-3 w-3" />
                        {new Date(task.due_date).toLocaleDateString("pt-BR")}
                      </span>
                    )}
                    {task.blocks_stages?.length > 0 && (
                      <span className="text-xs text-amber-600">Bloqueia: {task.blocks_stages.join(", ")}</span>
                    )}
                  </div>
                </div>

                {task.status !== "concluida" && (
                  <div className="flex gap-2 shrink-0">
                    {task.task_type === "approval" ? (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => openActionDialog(task, "approve")}
                          data-testid={`approve-btn-${task.id}`}
                        >
                          <ShieldCheck className="h-3.5 w-3.5 mr-1" />
                          Aprovar
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => openActionDialog(task, "reject")}
                          data-testid={`reject-btn-${task.id}`}
                        >
                          <ShieldX className="h-3.5 w-3.5 mr-1" />
                          Reprovar
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openActionDialog(task, "complete")}
                        data-testid={`complete-btn-${task.id}`}
                      >
                        Concluir
                      </Button>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Dialog open={actionOpen} onOpenChange={setActionOpen}>
        <DialogContent data-testid="task-action-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">{getDialogTitle(actionMode)}</DialogTitle>
            <DialogDescription>{getDialogDescription(actionMode)}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{activeTask?.title}</p>
            <div className="space-y-2">
              <Label>{actionMode === "reject" ? "Justificativa *" : "Comentario"}</Label>
              <Textarea
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder={getDialogPlaceholder(actionMode)}
                rows={4}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setActionOpen(false)}>
              Cancelar
            </Button>
            <Button
              variant={actionMode === "reject" ? "destructive" : "default"}
              onClick={submitAction}
            >
              Confirmar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Criar Tarefa Manual Dialog */}
      {showCreateTask && (
        <Dialog open onOpenChange={() => setShowCreateTask(false)}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2"><Plus className="h-4 w-4" />Criar Tarefa Manual</DialogTitle>
              <DialogDescription>Cria uma tarefa vinculada a uma entidade do sistema.</DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <div>
                <Label className="text-xs text-muted-foreground">Título *</Label>
                <Input value={createForm.title} onChange={e => setCreateForm(p => ({ ...p, title: e.target.value }))} placeholder="Título da tarefa" className="mt-1" data-testid="create-task-title" />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">Descrição</Label>
                <Textarea value={createForm.description} onChange={e => setCreateForm(p => ({ ...p, description: e.target.value }))} placeholder="Detalhes da tarefa..." rows={2} className="mt-1" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs text-muted-foreground">Tipo de Entidade</Label>
                  <Select value={createForm.entity_type} onValueChange={v => setCreateForm(p => ({ ...p, entity_type: v }))}>
                    <SelectTrigger className="mt-1 h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.entries(ENTITY_LABEL).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">ID da Entidade *</Label>
                  <Input value={createForm.entity_id} onChange={e => setCreateForm(p => ({ ...p, entity_id: e.target.value }))} placeholder="ID do card/projeto..." className="mt-1 h-8 text-xs" data-testid="create-task-entity-id" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs text-muted-foreground">Prazo (dias)</Label>
                  <Input type="number" value={createForm.due_in_days} onChange={e => setCreateForm(p => ({ ...p, due_in_days: e.target.value }))} className="mt-1 h-8 text-xs" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Prioridade</Label>
                  <Select value={createForm.priority} onValueChange={v => setCreateForm(p => ({ ...p, priority: v }))}>
                    <SelectTrigger className="mt-1 h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="baixa">Baixa</SelectItem>
                      <SelectItem value="normal">Normal</SelectItem>
                      <SelectItem value="alta">Alta</SelectItem>
                      <SelectItem value="critica">Crítica</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="blocking-check" checked={createForm.blocking} onChange={e => setCreateForm(p => ({ ...p, blocking: e.target.checked }))} className="rounded" />
                <Label htmlFor="blocking-check" className="text-sm cursor-pointer">Tarefa bloqueante (impede transição de status)</Label>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowCreateTask(false)}>Cancelar</Button>
              <Button onClick={submitCreateTask} disabled={creatingTask} data-testid="confirm-create-task-btn">
                {creatingTask ? "Criando..." : "Criar Tarefa"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

function getParamsForView(viewMode, isLeader) {
  switch (viewMode) {
    case "mine":
      return { mine: true };
    case "overdue":
      return { mine: true, overdue: true };
    case "week":
      return { mine: true, due_within_days: 7 };
    case "blocking":
      return isLeader ? { blocking: true } : { mine: true, blocking: true };
    case "done":
      return isLeader ? { status: "concluida" } : { mine: true, status: "concluida" };
    case "all":
      return isLeader ? {} : { mine: true };
    default:
      return { mine: true };
  }
}

function getDueClass(dueDate, status) {
  if (status === "concluida") return "text-muted-foreground";
  if (!dueDate) return "text-muted-foreground";
  const due = new Date(dueDate).getTime();
  const now = Date.now();
  if (due < now) return "text-destructive font-semibold";
  if (due - now < 24 * 3600 * 1000) return "text-amber-600";
  return "text-muted-foreground";
}

function getDialogTitle(mode) {
  if (mode === "approve") return "Aprovar tarefa";
  if (mode === "reject") return "Reprovar tarefa";
  return "Concluir tarefa";
}

function getDialogDescription(mode) {
  if (mode === "approve") return "Registre a aprovacao formal desta tarefa.";
  if (mode === "reject") return "A reprovacao exige uma justificativa rastreavel.";
  return "Confirme a conclusao da tarefa com comentario opcional.";
}

function getDialogPlaceholder(mode) {
  if (mode === "approve") return "Ex.: CQ aprovado para envio ao comercial";
  if (mode === "reject") return "Explique por que a tarefa foi reprovada";
  return "Ex.: atividade concluida sem pendencias";
}
