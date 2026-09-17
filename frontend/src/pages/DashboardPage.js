import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Users, Target, ListTodo, Loader2, FlaskConical, AlertTriangle,
  Clock3, Building2, ShoppingCart, Microscope, Package, CheckCircle2,
  Beaker, ChevronRight, TrendingUp, TrendingDown, Activity,
  FileText, DollarSign, Truck, BarChart3, ShieldCheck, Hourglass,
  ClipboardList, Award, Boxes, RefreshCw, ArrowUpRight,
} from "lucide-react";
import { toast } from "sonner";

// ─── helpers ────────────────────────────────────────────────────────────────

function fmt(n) {
  if (n == null) return "—";
  return n.toLocaleString("pt-BR");
}

function fmtBRL(n) {
  if (!n) return "R$ 0";
  if (n >= 1_000_000) return `R$ ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `R$ ${(n / 1_000).toFixed(1)}k`;
  return `R$ ${n.toFixed(0)}`;
}

const ROLE_GROUPS = {
  admin: "admin",
  vendedor: "comercial",
  sales_ops: "comercial",
  sucesso_cliente: "comercial",
  formulador: "pd",
  lider_pd: "pd",
  qa: "cq",
  engenharia_produto: "cq",
  compras: "compras",
};

// ─── KPI Card ───────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, Icon, tone = "default", onClick, alert }) {
  const tones = {
    default: "bg-card border-border",
    blue: "bg-blue-500/8 border-blue-200 dark:border-blue-900",
    indigo: "bg-indigo-500/8 border-indigo-200 dark:border-indigo-900",
    violet: "bg-violet-500/8 border-violet-200 dark:border-violet-900",
    amber: "bg-amber-500/8 border-amber-200 dark:border-amber-900",
    green: "bg-emerald-500/8 border-emerald-200 dark:border-emerald-900",
    red: "bg-red-500/8 border-red-200 dark:border-red-900",
    orange: "bg-orange-500/8 border-orange-200 dark:border-orange-900",
    cyan: "bg-cyan-500/8 border-cyan-200 dark:border-cyan-900",
    slate: "bg-slate-500/8 border-slate-200 dark:border-slate-900",
  };
  const iconColors = {
    default: "text-muted-foreground", blue: "text-blue-500", indigo: "text-indigo-500",
    violet: "text-violet-500", amber: "text-amber-500", green: "text-emerald-600",
    red: "text-red-500", orange: "text-orange-500", cyan: "text-cyan-600",
    slate: "text-slate-500",
  };
  return (
    <div
      className={`dashboard-kpi rounded-xl border px-4 py-3.5 flex items-center gap-3 transition-all ${tones[tone]} ${onClick ? "cursor-pointer hover:-translate-y-0.5 hover:shadow-md" : ""}`}
      onClick={onClick}
    >
      {Icon && (
        <div className={`p-2 rounded-lg ${tones[tone]} shrink-0`}>
          <Icon className={`h-4 w-4 ${iconColors[tone]}`} />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="font-mono text-2xl font-bold leading-none tabular-nums">{value ?? "—"}</p>
        <p className="text-[11px] text-muted-foreground mt-0.5 leading-tight">{label}</p>
        {sub && <p className={`text-[10px] mt-0.5 ${alert ? "text-red-500 font-medium" : "text-muted-foreground"}`}>{sub}</p>}
      </div>
      {onClick && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
    </div>
  );
}

// ─── Section wrapper ─────────────────────────────────────────────────────────

function Section({ title, Icon, accent, navPath, navigate, children, cols = 4 }) {
  const colMap = { 2: "grid-cols-2", 3: "grid-cols-2 sm:grid-cols-3", 4: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4", 5: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5", 6: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" };
  return (
    <div className="dashboard-panel border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b bg-muted/20">
        <div className="flex items-center gap-2.5">
          <span className={`w-1 h-4 ${accent} rounded-full`} />
          {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground" />}
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{title}</p>
        </div>
        {navPath && (
          <button onClick={() => navigate(navPath)} className="flex items-center gap-1 text-[10px] text-primary hover:underline font-medium">
            Ver tudo <ChevronRight className="h-3 w-3" />
          </button>
        )}
      </div>
      <div className={`px-5 py-4 grid gap-3 ${colMap[cols]}`}>
        {children}
      </div>
    </div>
  );
}

// ─── Funnel bar ──────────────────────────────────────────────────────────────

function FunnelRow({ label, value, total, color }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted-foreground w-32 shrink-0 truncate">{label}</span>
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs font-medium w-5 text-right">{value}</span>
    </div>
  );
}

// ─── Task queue ──────────────────────────────────────────────────────────────

function TaskQueue({ tasks, navigate }) {
  const now = Date.now();
  const open = tasks.filter(t => t.status !== "concluida");
  const overdue = open.filter(t => t.due_date && new Date(t.due_date).getTime() < now);
  const week = open.filter(t => {
    if (!t.due_date) return false;
    const d = new Date(t.due_date).getTime() - now;
    return d >= 0 && d <= 7 * 86_400_000;
  });

  return (
    <div className="dashboard-panel border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b bg-muted/20">
        <div className="flex items-center gap-2.5">
          <span className="w-1 h-4 bg-primary rounded-full" />
          <Activity className="h-3.5 w-3.5 text-muted-foreground" />
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Minhas Tarefas</p>
        </div>
        <button onClick={() => navigate("/tasks")} className="flex items-center gap-1 text-[10px] text-primary hover:underline font-medium">
          Ver todas <ChevronRight className="h-3 w-3" />
        </button>
      </div>
      <div className="px-5 py-4">
        <div className="grid grid-cols-3 gap-3 mb-4">
          {[
            { n: open.length, label: "Em aberto", tone: "" },
            { n: overdue.length, label: "Atrasadas", tone: overdue.length > 0 ? "text-red-500" : "" },
            { n: week.length, label: "Esta semana", tone: "" },
          ].map(({ n, label, tone }) => (
            <div key={label} className={`rounded-lg border px-4 py-3 text-center ${tone === "text-red-500" && n > 0 ? "border-red-200 bg-red-500/5 dark:border-red-900" : ""}`}>
              <p className={`text-2xl font-bold tabular-nums ${tone && n > 0 ? tone : ""}`}>{n}</p>
              <p className="text-[11px] text-muted-foreground mt-0.5">{label}</p>
            </div>
          ))}
        </div>
        {open.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-1">
            <CheckCircle2 className="h-4 w-4 text-green-500" /> Nenhuma tarefa pendente.
          </div>
        ) : (
          <div className="space-y-1.5">
            {open.slice(0, 5).map(task => (
              <button key={task.id} onClick={() => navigate("/tasks")}
                className="w-full rounded-lg border px-3.5 py-2.5 text-left hover:bg-accent transition-colors flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{task.title}</p>
                  <p className="text-[10px] text-muted-foreground">{task.entity_type} · {task.category || "geral"}</p>
                </div>
                <Badge variant={task.status === "em_atraso" ? "destructive" : task.blocking ? "destructive" : "outline"} className="shrink-0 text-[10px]">
                  {task.due_date ? new Date(task.due_date).toLocaleDateString("pt-BR") : "Sem prazo"}
                </Badge>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Alert strip ─────────────────────────────────────────────────────────────

function AlertStrip({ items }) {
  const active = items.filter(a => a.count > 0);
  if (!active.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {active.map(a => (
        <Badge key={a.label} className="gap-1.5 px-3 py-1.5 text-xs bg-red-500/10 text-red-600 border-red-200 dark:border-red-900">
          <AlertTriangle className="h-3.5 w-3.5" />
          {a.count} {a.label}
        </Badge>
      ))}
    </div>
  );
}

// ─── Dashboard Views ──────────────────────────────────────────────────────────

function AdminDashboard({ erp, tasks, navigate }) {
  const { crm, pd, cq, compras, pedidos, faturamento, kickoffs, recebimento, contratos } = erp;
  return (
    <>
      <AlertStrip items={[
        { count: cq.rncs_abertas, label: "RNC(s) aberta(s)" },
        { count: faturamento.duplicatas_vencidas, label: "duplicata(s) vencida(s)" },
        { count: compras.pos_atrasadas, label: "PO(s) atrasada(s)" },
        { count: pd.waiting_approval, label: "P&D aguardando aprovação" },
      ]} />

      {/* Hero strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Clientes Ativos" value={fmt(crm.clientes_ativos)} Icon={Users} tone="blue" onClick={() => navigate("/crm/clients")} />
        <KpiCard label="Projetos Ativos" value={fmt(crm.projetos_ativos)} Icon={Target} tone="indigo" onClick={() => navigate("/crm/projects")} />
        <KpiCard label="P&D em Andamento" value={fmt(pd.ativos)} Icon={FlaskConical} tone="violet" onClick={() => navigate("/pd")} />
        <KpiCard label="Kickoffs" value={fmt(kickoffs.total)} sub={`${kickoffs.aguardando_aprovacao} aguard. aprovação`} Icon={ClipboardList} tone="amber" onClick={() => navigate("/kickoffs")} />
        <KpiCard label="Pedidos Abertos" value={fmt(pedidos.abertos)} sub={`${pedidos.em_producao} em produção`} Icon={ShoppingCart} tone="green" onClick={() => navigate("/orders")} />
        <KpiCard label="Em Aberto (Fat.)" value={fmtBRL(faturamento.total_em_aberto)} sub={faturamento.total_vencido > 0 ? `${fmtBRL(faturamento.total_vencido)} vencido` : undefined} Icon={DollarSign} tone={faturamento.total_vencido > 0 ? "red" : "green"} alert={faturamento.total_vencido > 0} onClick={() => navigate("/faturamento")} />
      </div>

      <TaskQueue tasks={tasks} navigate={navigate} />

      {/* CRM */}
      <Section title="CRM Comercial" Icon={Building2} accent="bg-blue-500" navPath="/crm/clients" navigate={navigate} cols={4}>
        <KpiCard label="Total Clientes" value={fmt(crm.total_clientes)} Icon={Users} tone="blue" />
        <KpiCard label="Projetos Ativos" value={fmt(crm.projetos_ativos)} Icon={Target} tone="indigo" />
        <KpiCard label="Prontos p/ Kickoff" value={fmt(crm.projetos_pedido_aprovado)} Icon={Award} tone="green" />
        <KpiCard label="Amostras em Andamento" value={fmt(crm.amostras_andamento)} Icon={Beaker} tone="amber" />
      </Section>

      {/* P&D */}
      <Section title="Pesquisa & Desenvolvimento" Icon={FlaskConical} accent="bg-violet-500" navPath="/pd" navigate={navigate} cols={5}>
        <KpiCard label="Aberto" value={fmt(pd.open)} Icon={Clock3} tone="slate" />
        <KpiCard label="Em Desenvolvimento" value={fmt(pd.in_progress)} Icon={Beaker} tone="amber" />
        <KpiCard label="Em Testes" value={fmt(pd.in_tests)} Icon={FlaskConical} tone="violet" />
        <KpiCard label="Aguard. Aprovação" value={fmt(pd.waiting_approval)} Icon={Hourglass} tone={pd.waiting_approval > 0 ? "orange" : "slate"} />
        <KpiCard label="Aprovados" value={fmt(pd.approved)} Icon={CheckCircle2} tone="green" />
      </Section>

      {/* 3-col: Kickoffs | CQ | Compras */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="dashboard-panel border rounded-xl overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-3 border-b bg-muted/20">
            <span className="w-1 h-4 bg-amber-500 rounded-full" />
            <ClipboardList className="h-3.5 w-3.5 text-muted-foreground" />
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Kickoffs</p>
            <button onClick={() => navigate("/kickoffs")} className="ml-auto flex items-center gap-1 text-[10px] text-primary hover:underline font-medium">Ver <ChevronRight className="h-3 w-3" /></button>
          </div>
          <div className="px-5 py-4 space-y-3">
            <FunnelRow label="Em Preenchimento" value={kickoffs.em_preenchimento} total={kickoffs.total || 1} color="bg-amber-400" />
            <FunnelRow label="Aguard. Aprovação" value={kickoffs.aguardando_aprovacao} total={kickoffs.total || 1} color="bg-orange-400" />
            <FunnelRow label="Aprovados" value={kickoffs.aprovados} total={kickoffs.total || 1} color="bg-green-500" />
          </div>
        </div>

        <div className="dashboard-panel border rounded-xl overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-3 border-b bg-muted/20">
            <span className="w-1 h-4 bg-cyan-500 rounded-full" />
            <Microscope className="h-3.5 w-3.5 text-muted-foreground" />
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Controle de Qualidade</p>
            <button onClick={() => navigate("/cq")} className="ml-auto flex items-center gap-1 text-[10px] text-primary hover:underline font-medium">Ver <ChevronRight className="h-3 w-3" /></button>
          </div>
          <div className="px-5 py-4 space-y-2.5">
            {[
              { label: "RAs Pendentes", value: cq.ras_pendentes, alert: cq.ras_pendentes > 0 },
              { label: "RNCs Abertas", value: cq.rncs_abertas, alert: cq.rncs_abertas > 0 },
              { label: "Checklists Pendentes", value: cq.checklists_pendentes, alert: false },
              { label: "Retenções em Guarda", value: cq.retencoes_ativas, alert: false },
            ].map(({ label, value, alert }) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{label}</span>
                <span className={`font-semibold tabular-nums text-sm ${alert && value > 0 ? "text-red-500" : ""}`}>{value ?? 0}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="dashboard-panel border rounded-xl overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-3 border-b bg-muted/20">
            <span className="w-1 h-4 bg-orange-500 rounded-full" />
            <Package className="h-3.5 w-3.5 text-muted-foreground" />
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Compras</p>
            <button onClick={() => navigate("/compras")} className="ml-auto flex items-center gap-1 text-[10px] text-primary hover:underline font-medium">Ver <ChevronRight className="h-3 w-3" /></button>
          </div>
          <div className="px-5 py-4 space-y-2.5">
            {[
              { label: "Fornecedores Homologados", value: compras.fornecedores_homologados, alert: false },
              { label: "Em Avaliação", value: compras.fornecedores_em_avaliacao, alert: false },
              { label: "POs em Aberto", value: compras.pos_abertas, alert: compras.pos_abertas > 0 },
              { label: "POs Atrasadas", value: compras.pos_atrasadas, alert: compras.pos_atrasadas > 0 },
            ].map(({ label, value, alert }) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{label}</span>
                <span className={`font-semibold tabular-nums text-sm ${alert && value > 0 ? "text-amber-500" : ""}`}>{value ?? 0}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Faturamento + Contratos */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Section title="Faturamento" Icon={DollarSign} accent="bg-green-500" navPath="/faturamento" navigate={navigate} cols={2}>
          <KpiCard label="Duplicatas em Aberto" value={fmt(faturamento.duplicatas_abertas)} Icon={FileText} tone="amber" />
          <KpiCard label="Duplicatas Vencidas" value={fmt(faturamento.duplicatas_vencidas)} Icon={AlertTriangle} tone={faturamento.duplicatas_vencidas > 0 ? "red" : "slate"} alert={faturamento.duplicatas_vencidas > 0} />
          <KpiCard label="Total em Aberto" value={fmtBRL(faturamento.total_em_aberto)} Icon={TrendingUp} tone="green" />
          <KpiCard label="Total Vencido" value={fmtBRL(faturamento.total_vencido)} Icon={TrendingDown} tone={faturamento.total_vencido > 0 ? "red" : "slate"} alert={faturamento.total_vencido > 0} />
        </Section>
        <Section title="Contratos & Recebimento" Icon={FileText} accent="bg-indigo-500" cols={2}>
          <KpiCard label="Contratos CGI" value={fmt(contratos.total)} Icon={FileText} tone="indigo" onClick={() => navigate("/contratos")} />
          <KpiCard label="Recebimentos Pendentes" value={fmt(recebimento.pendentes)} Icon={Truck} tone={recebimento.pendentes > 0 ? "amber" : "slate"} onClick={() => navigate("/recebimento")} />
          <KpiCard label="Pedidos em Produção" value={fmt(pedidos.em_producao)} Icon={Boxes} tone="green" onClick={() => navigate("/orders")} />
          <KpiCard label="NFs Rascunho" value={fmt(faturamento.nfs_rascunho)} Icon={FileText} tone="slate" onClick={() => navigate("/faturamento")} />
        </Section>
      </div>
    </>
  );
}

function ComercialDashboard({ erp, tasks, navigate }) {
  const { crm, faturamento, kickoffs, contratos } = erp;
  return (
    <>
      <AlertStrip items={[
        { count: faturamento.duplicatas_vencidas, label: "duplicata(s) vencida(s)" },
      ]} />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Clientes Ativos" value={fmt(crm.clientes_ativos)} Icon={Users} tone="blue" onClick={() => navigate("/crm/clients")} />
        <KpiCard label="Projetos Ativos" value={fmt(crm.projetos_ativos)} sub={`${crm.projetos_pedido_aprovado} prontos p/ kickoff`} Icon={Target} tone="indigo" onClick={() => navigate("/crm/projects")} />
        <KpiCard label="Amostras em Andamento" value={fmt(crm.amostras_andamento)} Icon={Beaker} tone="amber" onClick={() => navigate("/crm/samples")} />
        <KpiCard label="A Receber" value={fmtBRL(faturamento.total_em_aberto)} sub={faturamento.total_vencido > 0 ? `${fmtBRL(faturamento.total_vencido)} vencido` : "Em dia"} Icon={DollarSign} tone={faturamento.total_vencido > 0 ? "red" : "green"} alert={faturamento.total_vencido > 0} onClick={() => navigate("/faturamento")} />
      </div>
      <TaskQueue tasks={tasks} navigate={navigate} />
      <Section title="Pipeline CRM" Icon={Building2} accent="bg-blue-500" navPath="/crm/clients" navigate={navigate} cols={3}>
        <KpiCard label="Total de Clientes" value={fmt(crm.total_clientes)} Icon={Users} tone="blue" />
        <KpiCard label="Total de Projetos" value={fmt(crm.total_projetos)} Icon={Target} tone="indigo" />
        <KpiCard label="Total de Amostras" value={fmt(crm.total_amostras)} Icon={Beaker} tone="amber" />
        <KpiCard label="Clientes Ativos" value={fmt(crm.clientes_ativos)} Icon={TrendingUp} tone="green" />
        <KpiCard label="Pedido Aprovado" value={fmt(crm.projetos_pedido_aprovado)} Icon={Award} tone="violet" />
        <KpiCard label="Amostras Ativas" value={fmt(crm.amostras_andamento)} Icon={Beaker} tone="amber" />
      </Section>
      <Section title="Kickoffs & Contratos" Icon={ClipboardList} accent="bg-amber-500" cols={4}>
        <KpiCard label="Em Preenchimento" value={fmt(kickoffs.em_preenchimento)} Icon={Clock3} tone="amber" onClick={() => navigate("/kickoffs")} />
        <KpiCard label="Aguard. Aprovação" value={fmt(kickoffs.aguardando_aprovacao)} Icon={Hourglass} tone="orange" onClick={() => navigate("/kickoffs")} />
        <KpiCard label="Kickoffs Aprovados" value={fmt(kickoffs.aprovados)} Icon={CheckCircle2} tone="green" onClick={() => navigate("/kickoffs")} />
        <KpiCard label="Contratos CGI" value={fmt(contratos.total)} Icon={FileText} tone="indigo" onClick={() => navigate("/contratos")} />
      </Section>
      <Section title="Contas a Receber" Icon={DollarSign} accent="bg-emerald-500" navPath="/faturamento" navigate={navigate} cols={4}>
        <KpiCard label="Duplicatas Abertas" value={fmt(faturamento.duplicatas_abertas)} Icon={FileText} tone="amber" />
        <KpiCard label="Duplicatas Vencidas" value={fmt(faturamento.duplicatas_vencidas)} Icon={AlertTriangle} tone={faturamento.duplicatas_vencidas > 0 ? "red" : "slate"} alert />
        <KpiCard label="Total em Aberto" value={fmtBRL(faturamento.total_em_aberto)} Icon={TrendingUp} tone="green" />
        <KpiCard label="Total Vencido" value={fmtBRL(faturamento.total_vencido)} Icon={TrendingDown} tone={faturamento.total_vencido > 0 ? "red" : "slate"} alert={faturamento.total_vencido > 0} />
      </Section>
    </>
  );
}

function PdDashboard({ erp, tasks, navigate, role }) {
  const { pd, kickoffs } = erp;
  const pd_ativo = pd.in_progress + pd.in_tests + pd.waiting_approval;
  return (
    <>
      <AlertStrip items={[
        { count: pd.waiting_approval, label: "P&D aguardando aprovação comercial" },
        { count: kickoffs.aguardando_aprovacao, label: "kickoff(s) aguardando aprovação" },
      ]} />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="P&D Ativo" value={fmt(pd_ativo)} sub="dev + testes + aprovação" Icon={FlaskConical} tone="violet" onClick={() => navigate("/pd")} />
        <KpiCard label="Em Desenvolvimento" value={fmt(pd.in_progress)} Icon={Beaker} tone="amber" onClick={() => navigate("/pd")} />
        <KpiCard label="Em Testes" value={fmt(pd.in_tests)} Icon={Microscope} tone="cyan" onClick={() => navigate("/pd")} />
        <KpiCard label="Fórmulas Registradas" value={fmt(pd.formulas)} Icon={FlaskConical} tone="indigo" onClick={() => navigate("/pd")} />
      </div>
      <TaskQueue tasks={tasks} navigate={navigate} />
      <Section title="Funil de P&D" Icon={BarChart3} accent="bg-violet-500" navPath="/pd" navigate={navigate} cols={3}>
        <KpiCard label="Abertos" value={fmt(pd.open)} Icon={Clock3} tone="slate" />
        <KpiCard label="Em Desenvolvimento" value={fmt(pd.in_progress)} Icon={Beaker} tone="amber" />
        <KpiCard label="Em Testes" value={fmt(pd.in_tests)} Icon={FlaskConical} tone="violet" />
        <KpiCard label="Aguard. Aprovação" value={fmt(pd.waiting_approval)} Icon={Hourglass} tone={pd.waiting_approval > 0 ? "orange" : "slate"} />
        <KpiCard label="Aprovados" value={fmt(pd.approved)} Icon={CheckCircle2} tone="green" />
        <KpiCard label="Concluídos" value={fmt(pd.completed)} Icon={Award} tone="cyan" />
      </Section>
      <Section title="Kickoffs" Icon={ClipboardList} accent="bg-amber-500" navPath="/kickoffs" navigate={navigate} cols={3}>
        <KpiCard label="Em Preenchimento" value={fmt(kickoffs.em_preenchimento)} Icon={Clock3} tone="amber" />
        <KpiCard label="Aguard. Aprovação" value={fmt(kickoffs.aguardando_aprovacao)} Icon={Hourglass} tone={kickoffs.aguardando_aprovacao > 0 ? "orange" : "slate"} />
        <KpiCard label="Aprovados" value={fmt(kickoffs.aprovados)} Icon={CheckCircle2} tone="green" />
      </Section>
    </>
  );
}

function CqDashboard({ erp, tasks, navigate }) {
  const { cq, kickoffs, pedidos } = erp;
  return (
    <>
      <AlertStrip items={[
        { count: cq.rncs_abertas, label: "RNC(s) aberta(s)" },
        { count: cq.ras_pendentes, label: "RA(s) pendente(s)" },
      ]} />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="RAs Pendentes" value={fmt(cq.ras_pendentes)} Icon={Microscope} tone={cq.ras_pendentes > 0 ? "amber" : "cyan"} alert={cq.ras_pendentes > 0} onClick={() => navigate("/cq")} />
        <KpiCard label="RNCs Abertas" value={fmt(cq.rncs_abertas)} Icon={AlertTriangle} tone={cq.rncs_abertas > 0 ? "red" : "slate"} alert={cq.rncs_abertas > 0} onClick={() => navigate("/cq")} />
        <KpiCard label="Checklists Pendentes" value={fmt(cq.checklists_pendentes)} Icon={ClipboardList} tone={cq.checklists_pendentes > 0 ? "orange" : "slate"} onClick={() => navigate("/cq")} />
        <KpiCard label="Retenções em Guarda" value={fmt(cq.retencoes_ativas)} Icon={ShieldCheck} tone="cyan" onClick={() => navigate("/cq")} />
      </div>
      <TaskQueue tasks={tasks} navigate={navigate} />
      <Section title="Detalhamento CQ" Icon={Microscope} accent="bg-cyan-500" navPath="/cq" navigate={navigate} cols={4}>
        <KpiCard label="RAs Pendentes" value={fmt(cq.ras_pendentes)} Icon={Clock3} tone="amber" />
        <KpiCard label="RAs Aprovadas" value={fmt(cq.ras_aprovadas)} Icon={CheckCircle2} tone="green" />
        <KpiCard label="RNCs em Tratamento" value={fmt(cq.rncs_abertas)} Icon={AlertTriangle} tone={cq.rncs_abertas > 0 ? "red" : "slate"} />
        <KpiCard label="Retenções" value={fmt(cq.retencoes_ativas)} Icon={ShieldCheck} tone="cyan" />
      </Section>
      <Section title="Kickoffs para Revisão Técnica" Icon={ClipboardList} accent="bg-amber-500" navPath="/kickoffs" navigate={navigate} cols={3}>
        <KpiCard label="Em Preenchimento" value={fmt(kickoffs.em_preenchimento)} Icon={Clock3} tone="amber" />
        <KpiCard label="Aguard. Aprovação" value={fmt(kickoffs.aguardando_aprovacao)} Icon={Hourglass} tone={kickoffs.aguardando_aprovacao > 0 ? "orange" : "slate"} />
        <KpiCard label="Pedidos em Produção" value={fmt(pedidos.em_producao)} Icon={Boxes} tone="green" onClick={() => navigate("/orders")} />
      </Section>
    </>
  );
}

function ComprasDashboard({ erp, tasks, navigate }) {
  const { compras, recebimento, pedidos } = erp;
  return (
    <>
      <AlertStrip items={[
        { count: compras.pos_atrasadas, label: "PO(s) atrasada(s)" },
        { count: recebimento.pendentes, label: "recebimento(s) pendente(s)" },
      ]} />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Fornecedores Homologados" value={fmt(compras.fornecedores_homologados)} Icon={ShieldCheck} tone="green" onClick={() => navigate("/compras")} />
        <KpiCard label="POs em Aberto" value={fmt(compras.pos_abertas)} sub={compras.pos_atrasadas > 0 ? `${compras.pos_atrasadas} atrasada(s)` : "Em dia"} Icon={Package} tone={compras.pos_atrasadas > 0 ? "red" : "amber"} alert={compras.pos_atrasadas > 0} onClick={() => navigate("/compras")} />
        <KpiCard label="Em Avaliação" value={fmt(compras.fornecedores_em_avaliacao)} Icon={Clock3} tone="orange" onClick={() => navigate("/compras")} />
        <KpiCard label="Recebimentos Pendentes" value={fmt(recebimento.pendentes)} Icon={Truck} tone={recebimento.pendentes > 0 ? "amber" : "slate"} onClick={() => navigate("/recebimento")} />
      </div>
      <TaskQueue tasks={tasks} navigate={navigate} />
      <Section title="Fornecedores" Icon={Building2} accent="bg-orange-500" navPath="/compras" navigate={navigate} cols={3}>
        <KpiCard label="Homologados" value={fmt(compras.fornecedores_homologados)} Icon={CheckCircle2} tone="green" />
        <KpiCard label="Em Avaliação" value={fmt(compras.fornecedores_em_avaliacao)} Icon={Clock3} tone="amber" />
        <KpiCard label="POs Abertas" value={fmt(compras.pos_abertas)} Icon={Package} tone="orange" />
      </Section>
      <Section title="Recebimento & Produção" Icon={Truck} accent="bg-blue-500" cols={3}>
        <KpiCard label="Recebimentos Pendentes" value={fmt(recebimento.pendentes)} Icon={Truck} tone="amber" onClick={() => navigate("/recebimento")} />
        <KpiCard label="Pedidos em Aberto" value={fmt(pedidos.abertos)} Icon={ShoppingCart} tone="indigo" onClick={() => navigate("/orders")} />
        <KpiCard label="Em Produção" value={fmt(pedidos.em_producao)} Icon={Boxes} tone="green" onClick={() => navigate("/orders")} />
      </Section>
    </>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [erp, setErp] = useState(null);
  const [myTasks, setMyTasks] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = () => {
    setLoading(true);
    Promise.all([
      api.get("/erp-overview").then(({ data }) => setErp(data)).catch(() => setErp(null)),
      api.get("/workflow/tasks", { params: { mine: true } }).then(({ data }) => setMyTasks(data || [])).catch(() => setMyTasks([])),
    ]).finally(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, []);

  const roleGroup = ROLE_GROUPS[user?.role] || "admin";

  const greetings = {
    admin: "Visão Executiva",
    comercial: "Pipeline Comercial",
    pd: "Central P&D",
    cq: "Controle de Qualidade",
    compras: "Gestão de Compras",
  };

  if (loading) {
    return (
      <div className="p-8">
        <div className="animate-pulse space-y-6">
          <div className="h-8 w-56 rounded bg-muted" />
          <div className="grid grid-cols-4 gap-4">{[1,2,3,4].map(i=><div key={i} className="h-24 rounded-xl bg-muted"/>)}</div>
          <div className="space-y-4">{[1,2,3].map(i=><div key={i} className="h-36 rounded-xl bg-muted"/>)}</div>
        </div>
      </div>
    );
  }

  if (!erp) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        <p>Falha ao carregar dados do dashboard.</p>
        <Button variant="outline" className="mt-4 gap-2" onClick={fetchAll}>
          <RefreshCw className="h-4 w-4" /> Tentar novamente
        </Button>
      </div>
    );
  }

  return (
    <div className="dashboard-shell space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="dashboard-eyebrow">Kuryos ERP · Visão consolidada</p>
          <h1 className="dashboard-title font-heading">{greetings[roleGroup]}</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Olá, <span className="font-medium text-foreground">{user?.name}</span> · {new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" })}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchAll} className="gap-2 h-8">
          <RefreshCw className="h-3.5 w-3.5" /> Atualizar
        </Button>
      </div>

      {roleGroup === "admin"    && <AdminDashboard    erp={erp} tasks={myTasks} navigate={navigate} />}
      {roleGroup === "comercial"&& <ComercialDashboard erp={erp} tasks={myTasks} navigate={navigate} />}
      {roleGroup === "pd"       && <PdDashboard        erp={erp} tasks={myTasks} navigate={navigate} role={user?.role} />}
      {roleGroup === "cq"       && <CqDashboard        erp={erp} tasks={myTasks} navigate={navigate} />}
      {roleGroup === "compras"  && <ComprasDashboard   erp={erp} tasks={myTasks} navigate={navigate} />}
    </div>
  );
}
