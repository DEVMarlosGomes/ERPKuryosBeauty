import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
    Briefcase,
    CalendarDays,
    CheckCircle2,
    ClipboardCheck,
    Edit,
    Plus,
    Power,
    Search,
    Trash2,
    Users,
} from "lucide-react";

import api, { formatApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

const emptyDashboard = {
    headcount_ativo: 0,
    admissoes_30d: 0,
    desligamentos_30d: 0,
    turnover_30d: 0,
    por_sexo: {},
    por_tipo_contrato: {},
    custo_mensal: 0,
    media_avaliacoes: 0,
    ferias_pendentes: 0,
    alertas: [],
};

const emptyCargo = { nome: "", setor: "", nivel: "", descricao: "", ativo: true };
const emptyColaborador = {
    nome: "",
    cpf: "",
    email: "",
    telefone: "",
    cargo_id: "",
    cargo_nome: "",
    gestor_id: "",
    gestor_nome: "",
    sexo: "",
    tipo_contrato: "CLT",
    data_admissao: "",
    status: "Ativo",
    salario_base: 0,
    vale_transporte: 0,
    vale_alimentacao: 0,
    dados_pessoais: {},
    endereco: {},
    emergencia: {},
    observacoes: "",
};
const emptyAvaliacao = {
    colaborador_id: "",
    periodo: "",
    data: "",
    pontos_fortes: "",
    pontos_melhoria: "",
    comentario_colaborador: "",
    competencias: { entrega: 3, qualidade: 3, colaboracao: 3, postura: 3, desenvolvimento: 3 },
    status: "Registrada",
};
const emptyFerias = { colaborador_id: "", periodo_aquisitivo: "", data_inicio: "", data_fim: "", observacoes: "", status: "Solicitada" };

function money(value) {
    return Number(value || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function stat(label, value, icon) {
    return (
        <Card className="border-l-4 border-l-primary shadow-sm">
            <CardContent className="flex min-h-[96px] items-center justify-between p-5">
                <div>
                    <div className="text-3xl font-bold text-foreground">{value}</div>
                    <div className="mt-2 text-xs font-semibold uppercase text-muted-foreground">{label}</div>
                </div>
                <div className="rounded-md bg-primary/10 p-2 text-primary">{icon}</div>
            </CardContent>
        </Card>
    );
}

function SectionTitle({ title, subtitle }) {
    return (
        <div className="flex flex-col gap-1">
            <h1 className="text-3xl font-bold tracking-normal text-foreground">{title}</h1>
            {subtitle ? <p className="text-sm text-muted-foreground">{subtitle}</p> : null}
        </div>
    );
}

function EmptyState({ children }) {
    return <div className="py-10 text-center text-sm text-muted-foreground">{children}</div>;
}

export default function RHPage() {
    const [loading, setLoading] = useState(true);
    const [dashboard, setDashboard] = useState(emptyDashboard);
    const [colaboradores, setColaboradores] = useState([]);
    const [cargos, setCargos] = useState([]);
    const [avaliacoes, setAvaliacoes] = useState([]);
    const [ferias, setFerias] = useState([]);
    const [search, setSearch] = useState("");
    const [statusFilter, setStatusFilter] = useState("Todos");
    const [dialog, setDialog] = useState(null);
    const [saving, setSaving] = useState(false);

    async function load() {
        setLoading(true);
        try {
            const [dashRes, colRes, cargoRes, avaRes, feriasRes] = await Promise.all([
                api.get("/rh/dashboard"),
                api.get("/rh/colaboradores"),
                api.get("/rh/cargos"),
                api.get("/rh/avaliacoes"),
                api.get("/rh/ferias"),
            ]);
            setDashboard({ ...emptyDashboard, ...dashRes.data });
            setColaboradores(colRes.data || []);
            setCargos(cargoRes.data || []);
            setAvaliacoes(avaRes.data || []);
            setFerias(feriasRes.data || []);
        } catch (error) {
            toast.error(formatApiError(error?.response?.data?.detail || error));
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        load();
    }, []);

    const filteredColaboradores = useMemo(() => {
        const term = search.trim().toLowerCase();
        return colaboradores.filter((item) => {
            const matchText = !term || [item.nome, item.cpf, item.email, item.cargo_nome].filter(Boolean).join(" ").toLowerCase().includes(term);
            const matchStatus = statusFilter === "Todos" || item.status === statusFilter;
            return matchText && matchStatus;
        });
    }, [colaboradores, search, statusFilter]);

    const collaboratorName = (id) => colaboradores.find((c) => c.id === id)?.nome || "Colaborador";

    function openDialog(type, data) {
        const defaults = { cargo: emptyCargo, colaborador: emptyColaborador, avaliacao: emptyAvaliacao, ferias: emptyFerias };
        setDialog({ type, data: { ...defaults[type], ...(data || {}) }, editing: Boolean(data?.id) });
    }

    function setField(field, value) {
        setDialog((current) => ({ ...current, data: { ...current.data, [field]: value } }));
    }

    async function saveDialog() {
        if (!dialog) return;
        setSaving(true);
        try {
            const { type, data, editing } = dialog;
            const base = { cargo: "cargos", colaborador: "colaboradores", avaliacao: "avaliacoes", ferias: "ferias" }[type];
            const payload = { ...data };
            if (type === "colaborador") {
                const cargo = cargos.find((c) => c.id === payload.cargo_id);
                payload.cargo_nome = cargo?.nome || payload.cargo_nome || "";
            }
            if (editing) await api.put(`/rh/${base}/${data.id}`, payload);
            else await api.post(`/rh/${base}`, payload);
            toast.success("Registro salvo.");
            setDialog(null);
            await load();
        } catch (error) {
            toast.error(formatApiError(error?.response?.data?.detail || error));
        } finally {
            setSaving(false);
        }
    }

    async function remove(base, id) {
        try {
            await api.delete(`/rh/${base}/${id}`);
            toast.success("Registro excluido.");
            await load();
        } catch (error) {
            toast.error(formatApiError(error?.response?.data?.detail || error));
        }
    }

    async function post(path, success) {
        try {
            await api.post(path);
            toast.success(success);
            await load();
        } catch (error) {
            toast.error(formatApiError(error?.response?.data?.detail || error));
        }
    }

    const dialogTitle = {
        cargo: dialog?.editing ? "Editar cargo" : "Novo cargo",
        colaborador: dialog?.editing ? "Editar colaborador" : "Novo colaborador",
        avaliacao: dialog?.editing ? "Editar avaliacao" : "Registrar avaliacao",
        ferias: dialog?.editing ? "Editar ferias" : "Nova solicitacao de ferias",
    }[dialog?.type];

    return (
        <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 p-4 sm:p-6 lg:p-8">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <SectionTitle title="Recursos Humanos" subtitle="Dashboard, colaboradores, cargos, desempenho e ferias em um unico modulo." />
                <Badge variant="secondary" className="w-fit gap-2 rounded-full px-3 py-1">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" /> {loading ? "Sincronizando" : "Conectado"}
                </Badge>
            </div>

            <Tabs defaultValue="dashboard" className="w-full">
                <TabsList className="grid h-auto w-full grid-cols-2 gap-1 bg-muted p-1 md:grid-cols-5">
                    <TabsTrigger value="dashboard">Dash</TabsTrigger>
                    <TabsTrigger value="colaboradores">Colaboradores</TabsTrigger>
                    <TabsTrigger value="cargos">Cargos</TabsTrigger>
                    <TabsTrigger value="avaliacao">Avaliacao</TabsTrigger>
                    <TabsTrigger value="ferias">Ferias</TabsTrigger>
                </TabsList>

                <TabsContent value="dashboard" className="mt-6 space-y-6">
                    <SectionTitle title="Dashboard do RH" subtitle="Consolidado de cadastro, avaliacao e ferias." />
                    <Card className="border-l-4 border-l-primary">
                        <CardHeader className="pb-2"><CardTitle className="text-sm uppercase">Alertas</CardTitle></CardHeader>
                        <CardContent>
                            {dashboard.alertas?.length ? dashboard.alertas.map((a) => <p key={a} className="text-sm text-muted-foreground">{a}</p>) : <EmptyState>Nenhum alerta no momento.</EmptyState>}
                        </CardContent>
                    </Card>
                    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                        {stat("Headcount ativo", dashboard.headcount_ativo, <Users className="h-5 w-5" />)}
                        {stat("Admissoes (30d)", dashboard.admissoes_30d, <Plus className="h-5 w-5" />)}
                        {stat("Desligamentos (30d)", dashboard.desligamentos_30d, <Power className="h-5 w-5" />)}
                        {stat("Turnover (30d)", `${dashboard.turnover_30d}%`, <Briefcase className="h-5 w-5" />)}
                    </div>
                    <div className="grid gap-4 lg:grid-cols-2">
                        <GroupCard title="Por sexo" data={dashboard.por_sexo} />
                        <GroupCard title="Por tipo de contrato" data={dashboard.por_tipo_contrato} />
                    </div>
                    <div className="grid gap-4 md:grid-cols-3">
                        {stat("Custos de pessoal", money(dashboard.custo_mensal), <Briefcase className="h-5 w-5" />)}
                        {stat("Media de avaliacao", dashboard.media_avaliacoes || 0, <ClipboardCheck className="h-5 w-5" />)}
                        {stat("Ferias pendentes", dashboard.ferias_pendentes, <CalendarDays className="h-5 w-5" />)}
                    </div>
                </TabsContent>

                <TabsContent value="colaboradores" className="mt-6 space-y-5">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                        <SectionTitle title="Colaboradores" subtitle="Cadastro do colaborador e historico organizacional." />
                        <Button onClick={() => openDialog("colaborador")}><Plus className="mr-2 h-4 w-4" /> Novo colaborador</Button>
                    </div>
                    <div className="grid gap-3 md:grid-cols-[1fr_240px]">
                        <div className="relative">
                            <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                            <Input className="pl-9" placeholder="Buscar por nome, CPF, e-mail ou cargo..." value={search} onChange={(e) => setSearch(e.target.value)} />
                        </div>
                        <Select value={statusFilter} onValueChange={setStatusFilter}>
                            <SelectTrigger><SelectValue /></SelectTrigger>
                            <SelectContent>
                                {["Todos", "Ativo", "Afastado", "Desligado"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="grid gap-4 md:grid-cols-4">
                        {stat("Total", colaboradores.length, <Users className="h-5 w-5" />)}
                        {stat("Ativos", colaboradores.filter((c) => c.status === "Ativo").length, <CheckCircle2 className="h-5 w-5" />)}
                        {stat("Desligados", colaboradores.filter((c) => c.status === "Desligado").length, <Power className="h-5 w-5" />)}
                        {stat("CLT ativos", colaboradores.filter((c) => c.status === "Ativo" && c.tipo_contrato === "CLT").length, <Briefcase className="h-5 w-5" />)}
                    </div>
                    <Card className="overflow-hidden border-l-4 border-l-primary">
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[860px] text-sm">
                                <thead className="border-b bg-muted/60 text-xs uppercase text-muted-foreground">
                                    <tr><th className="p-3 text-left">Nome</th><th className="p-3 text-left">Cargo</th><th className="p-3 text-left">Contrato</th><th className="p-3 text-left">Admissao</th><th className="p-3 text-left">Status</th><th className="p-3 text-right">Acoes</th></tr>
                                </thead>
                                <tbody>
                                    {filteredColaboradores.map((item) => (
                                        <tr key={item.id} className="border-b last:border-0">
                                            <td className="p-3 font-medium">{item.nome}<div className="text-xs text-muted-foreground">{item.email || item.cpf}</div></td>
                                            <td className="p-3">{item.cargo_nome || "-"}</td>
                                            <td className="p-3">{item.tipo_contrato}</td>
                                            <td className="p-3">{item.data_admissao || "-"}</td>
                                            <td className="p-3"><Badge variant={item.status === "Ativo" ? "default" : "secondary"}>{item.status}</Badge></td>
                                            <td className="p-3 text-right"><RowActions onEdit={() => openDialog("colaborador", item)} onDelete={() => remove("colaboradores", item.id)} extra={item.status !== "Desligado" ? () => post(`/rh/colaboradores/${item.id}/desligar`, "Colaborador desligado.") : null} /></td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            {!filteredColaboradores.length ? <EmptyState>Nenhum colaborador cadastrado ainda.</EmptyState> : null}
                        </div>
                    </Card>
                </TabsContent>

                <TabsContent value="cargos" className="mt-6 space-y-5">
                    <div className="flex items-end justify-between gap-3">
                        <SectionTitle title="Cargos" subtitle="Estrutura organizacional e trilhas internas." />
                        <Button onClick={() => openDialog("cargo")}><Plus className="mr-2 h-4 w-4" /> Novo cargo</Button>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        {cargos.map((cargo) => (
                            <Card key={cargo.id} className="border-l-4 border-l-primary">
                                <CardHeader className="pb-3"><CardTitle className="flex items-start justify-between gap-3 text-base"><span>{cargo.nome}</span><Badge variant={cargo.ativo ? "default" : "secondary"}>{cargo.ativo ? "Ativo" : "Inativo"}</Badge></CardTitle></CardHeader>
                                <CardContent className="space-y-3 text-sm text-muted-foreground">
                                    <p>{cargo.descricao || "Sem descricao."}</p>
                                    <p>{cargo.setor || "Setor nao informado"} {cargo.nivel ? `- ${cargo.nivel}` : ""}</p>
                                    <RowActions onEdit={() => openDialog("cargo", cargo)} onDelete={() => remove("cargos", cargo.id)} />
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                    {!cargos.length ? <EmptyState>Nenhum cargo cadastrado.</EmptyState> : null}
                </TabsContent>

                <TabsContent value="avaliacao" className="mt-6 space-y-5">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                        <SectionTitle title="Avaliacao de Desempenho" subtitle="Modelo, registro por periodo e historico." />
                        <Button onClick={() => openDialog("avaliacao")}><Plus className="mr-2 h-4 w-4" /> Registrar avaliacao</Button>
                    </div>
                    <Card className="border-l-4 border-l-primary">
                        <CardHeader><CardTitle className="text-sm uppercase">Modelo de avaliacao</CardTitle></CardHeader>
                        <CardContent className="grid gap-3 md:grid-cols-5">
                            {["Entrega", "Qualidade", "Colaboracao", "Postura", "Desenvolvimento"].map((c) => <Badge key={c} variant="secondary" className="justify-center py-2">{c}</Badge>)}
                        </CardContent>
                    </Card>
                    <HistoryTable rows={avaliacoes} collaboratorName={collaboratorName} onEdit={(row) => openDialog("avaliacao", row)} onDelete={(id) => remove("avaliacoes", id)} />
                </TabsContent>

                <TabsContent value="ferias" className="mt-6 space-y-5">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                        <SectionTitle title="Ferias" subtitle="Solicitacao, aprovacao e historico em duas etapas." />
                        <Button onClick={() => openDialog("ferias")}><Plus className="mr-2 h-4 w-4" /> Nova solicitacao</Button>
                    </div>
                    <Card className="border-l-4 border-l-primary">
                        <CardContent className="p-4 text-sm text-muted-foreground">
                            Regra de saldo provisoria: 30 dias por periodo aquisitivo de 12 meses. Ajuste fino fica registrado na decisao do RH.
                        </CardContent>
                    </Card>
                    <VacationTable rows={ferias} collaboratorName={collaboratorName} onEdit={(row) => openDialog("ferias", row)} onDelete={(id) => remove("ferias", id)} onAction={post} />
                </TabsContent>
            </Tabs>

            <Dialog open={Boolean(dialog)} onOpenChange={(open) => !open && setDialog(null)}>
                <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
                    <DialogHeader><DialogTitle>{dialogTitle}</DialogTitle></DialogHeader>
                    {dialog ? <DialogForm dialog={dialog} cargos={cargos} colaboradores={colaboradores} setField={setField} /> : null}
                    <div className="flex justify-end gap-2 pt-2">
                        <Button variant="outline" onClick={() => setDialog(null)}>Cancelar</Button>
                        <Button onClick={saveDialog} disabled={saving}>{saving ? "Salvando..." : "Salvar"}</Button>
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    );
}

function GroupCard({ title, data }) {
    const rows = Object.entries(data || {});
    return (
        <Card className="border-l-4 border-l-primary">
            <CardHeader><CardTitle className="text-sm uppercase">{title}</CardTitle></CardHeader>
            <CardContent className="space-y-3">
                {rows.length ? rows.map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between rounded-md border bg-muted/30 px-3 py-2 text-sm">
                        <span>{label}</span><Badge variant="secondary">{value}</Badge>
                    </div>
                )) : <EmptyState>Sem dados.</EmptyState>}
            </CardContent>
        </Card>
    );
}

function RowActions({ onEdit, onDelete, extra }) {
    return (
        <div className="flex justify-end gap-1">
            <Button size="icon" variant="ghost" onClick={onEdit} title="Editar"><Edit className="h-4 w-4" /></Button>
            {extra ? <Button size="icon" variant="ghost" onClick={extra} title="Desligar"><Power className="h-4 w-4" /></Button> : null}
            <Button size="icon" variant="ghost" className="text-destructive hover:text-destructive" onClick={onDelete} title="Excluir"><Trash2 className="h-4 w-4" /></Button>
        </div>
    );
}

function DialogForm({ dialog, cargos, colaboradores, setField }) {
    const d = dialog.data;
    if (dialog.type === "cargo") {
        return <div className="grid gap-4 md:grid-cols-2"><Field label="Nome *" value={d.nome} onChange={(v) => setField("nome", v)} /><Field label="Setor" value={d.setor} onChange={(v) => setField("setor", v)} /><Field label="Nivel" value={d.nivel} onChange={(v) => setField("nivel", v)} /><SelectField label="Status" value={d.ativo ? "Ativo" : "Inativo"} options={["Ativo", "Inativo"]} onChange={(v) => setField("ativo", v === "Ativo")} /><Field className="md:col-span-2" textarea label="Descricao" value={d.descricao} onChange={(v) => setField("descricao", v)} /></div>;
    }
    if (dialog.type === "colaborador") {
        return (
            <div className="grid gap-4 md:grid-cols-2">
                <Field label="Nome *" value={d.nome} onChange={(v) => setField("nome", v)} /><Field label="CPF" value={d.cpf} onChange={(v) => setField("cpf", v)} />
                <Field label="E-mail" value={d.email} onChange={(v) => setField("email", v)} /><Field label="Telefone" value={d.telefone} onChange={(v) => setField("telefone", v)} />
                <SelectField label="Cargo" value={d.cargo_id || "manual"} options={["manual", ...cargos.map((c) => c.id)]} labels={{ manual: "Preenchimento manual", ...Object.fromEntries(cargos.map((c) => [c.id, c.nome])) }} onChange={(v) => setField("cargo_id", v === "manual" ? "" : v)} />
                <Field label="Cargo manual" value={d.cargo_nome} onChange={(v) => setField("cargo_nome", v)} />
                <SelectField label="Gestor direto" value={d.gestor_id || "nenhum"} options={["nenhum", ...colaboradores.map((c) => c.id)]} labels={{ nenhum: "Nao informado", ...Object.fromEntries(colaboradores.map((c) => [c.id, c.nome])) }} onChange={(v) => setField("gestor_id", v === "nenhum" ? "" : v)} />
                <SelectField label="Sexo" value={d.sexo || "Nao informado"} options={["Nao informado", "Feminino", "Masculino", "Outro"]} onChange={(v) => setField("sexo", v)} />
                <SelectField label="Contrato" value={d.tipo_contrato} options={["CLT", "Temporario", "Aprendiz", "Terceirizado", "PJ", "Outro"]} onChange={(v) => setField("tipo_contrato", v)} />
                <Field label="Admissao" type="date" value={d.data_admissao} onChange={(v) => setField("data_admissao", v)} />
                <Field label="Salario base" type="number" value={d.salario_base} onChange={(v) => setField("salario_base", Number(v || 0))} /><Field label="Vale transporte" type="number" value={d.vale_transporte} onChange={(v) => setField("vale_transporte", Number(v || 0))} />
                <Field label="Vale alimentacao" type="number" value={d.vale_alimentacao} onChange={(v) => setField("vale_alimentacao", Number(v || 0))} /><SelectField label="Status" value={d.status} options={["Ativo", "Afastado", "Desligado"]} onChange={(v) => setField("status", v)} />
                <Field className="md:col-span-2" textarea label="Observacoes" value={d.observacoes} onChange={(v) => setField("observacoes", v)} />
            </div>
        );
    }
    if (dialog.type === "avaliacao") {
        return (
            <div className="grid gap-4 md:grid-cols-2">
                <SelectField label="Colaborador *" value={d.colaborador_id || "nenhum"} options={["nenhum", ...colaboradores.map((c) => c.id)]} labels={{ nenhum: "Selecione...", ...Object.fromEntries(colaboradores.map((c) => [c.id, c.nome])) }} onChange={(v) => setField("colaborador_id", v === "nenhum" ? "" : v)} />
                <Field label="Periodo *" value={d.periodo} onChange={(v) => setField("periodo", v)} />
                <Field label="Data" type="date" value={d.data} onChange={(v) => setField("data", v)} />
                {Object.keys(d.competencias || {}).map((key) => <Field key={key} label={key} type="number" value={d.competencias[key]} onChange={(v) => setField("competencias", { ...d.competencias, [key]: Number(v || 0) })} />)}
                <Field className="md:col-span-2" textarea label="Pontos fortes" value={d.pontos_fortes} onChange={(v) => setField("pontos_fortes", v)} />
                <Field className="md:col-span-2" textarea label="Pontos de melhoria" value={d.pontos_melhoria} onChange={(v) => setField("pontos_melhoria", v)} />
                <Field className="md:col-span-2" textarea label="Comentario do colaborador" value={d.comentario_colaborador} onChange={(v) => setField("comentario_colaborador", v)} />
            </div>
        );
    }
    return (
        <div className="grid gap-4 md:grid-cols-2">
            <SelectField label="Colaborador *" value={d.colaborador_id || "nenhum"} options={["nenhum", ...colaboradores.map((c) => c.id)]} labels={{ nenhum: "Selecione...", ...Object.fromEntries(colaboradores.map((c) => [c.id, c.nome])) }} onChange={(v) => setField("colaborador_id", v === "nenhum" ? "" : v)} />
            <Field label="Periodo aquisitivo *" value={d.periodo_aquisitivo} onChange={(v) => setField("periodo_aquisitivo", v)} />
            <Field label="Data de inicio *" type="date" value={d.data_inicio} onChange={(v) => setField("data_inicio", v)} />
            <Field label="Data de fim *" type="date" value={d.data_fim} onChange={(v) => setField("data_fim", v)} />
            <SelectField label="Status" value={d.status} options={["Solicitada", "Em aprovacao", "Aprovada", "Reprovada", "Cancelada"]} onChange={(v) => setField("status", v)} />
            <Field className="md:col-span-2" textarea label="Observacoes" value={d.observacoes} onChange={(v) => setField("observacoes", v)} />
        </div>
    );
}

function Field({ label, value, onChange, type = "text", textarea, className = "" }) {
    return <div className={className}><Label>{label}</Label>{textarea ? <Textarea value={value || ""} onChange={(e) => onChange(e.target.value)} /> : <Input type={type} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />}</div>;
}

function SelectField({ label, value, options, labels = {}, onChange }) {
    return (
        <div><Label>{label}</Label><Select value={String(value || options[0])} onValueChange={onChange}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{options.map((o) => <SelectItem key={o} value={String(o)}>{labels[o] || o}</SelectItem>)}</SelectContent></Select></div>
    );
}

function HistoryTable({ rows, collaboratorName, onEdit, onDelete }) {
    return (
        <Card className="overflow-hidden border-l-4 border-l-primary"><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead className="border-b bg-muted/60 text-xs uppercase text-muted-foreground"><tr><th className="p-3 text-left">Colaborador</th><th className="p-3 text-left">Periodo</th><th className="p-3 text-left">Data</th><th className="p-3 text-left">Nota</th><th className="p-3 text-right">Acoes</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-b last:border-0"><td className="p-3 font-medium">{collaboratorName(row.colaborador_id)}</td><td className="p-3">{row.periodo}</td><td className="p-3">{row.data || "-"}</td><td className="p-3"><Badge variant="secondary">{row.nota_geral || 0}</Badge></td><td className="p-3"><RowActions onEdit={() => onEdit(row)} onDelete={() => onDelete(row.id)} /></td></tr>)}</tbody></table>{!rows.length ? <EmptyState>Nenhuma avaliacao registrada.</EmptyState> : null}</div></Card>
    );
}

function VacationTable({ rows, collaboratorName, onEdit, onDelete, onAction }) {
    return (
        <Card className="overflow-hidden border-l-4 border-l-primary"><div className="overflow-x-auto"><table className="w-full min-w-[860px] text-sm"><thead className="border-b bg-muted/60 text-xs uppercase text-muted-foreground"><tr><th className="p-3 text-left">Colaborador</th><th className="p-3 text-left">Periodo</th><th className="p-3 text-left">Inicio</th><th className="p-3 text-left">Fim</th><th className="p-3 text-left">Status</th><th className="p-3 text-right">Acoes</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-b last:border-0"><td className="p-3 font-medium">{collaboratorName(row.colaborador_id)}</td><td className="p-3">{row.periodo_aquisitivo}</td><td className="p-3">{row.data_inicio}</td><td className="p-3">{row.data_fim}</td><td className="p-3"><Badge variant="secondary">{row.status}</Badge></td><td className="p-3"><div className="flex justify-end gap-1"><Button size="sm" variant="outline" onClick={() => onAction(`/rh/ferias/${row.id}/aprovar`, "Ferias aprovadas.")}>Aprovar</Button><Button size="icon" variant="ghost" onClick={() => onEdit(row)}><Edit className="h-4 w-4" /></Button><Button size="icon" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => onDelete(row.id)}><Trash2 className="h-4 w-4" /></Button></div></td></tr>)}</tbody></table>{!rows.length ? <EmptyState>Nenhuma solicitacao registrada.</EmptyState> : null}</div></Card>
    );
}
