import { useState, useEffect, useCallback, useMemo } from "react";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { indexToLetters } from "@/lib/letters";
import {
    DEFAULT_PRICE_DISPLAY,
    DEFAULT_VOLUME_DISPLAY,
    fmtPriceDisplay,
    fmtVolumeDisplay,
    parsePriceInput,
    parseVolumeInput,
    seedPriceDisplay,
    seedVolumeDisplay,
} from "@/lib/masks";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { GripVertical, Building2, PackagePlus, Archive, ChevronRight, FlaskConical, ExternalLink, ShoppingCart, CheckCircle, XCircle } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import SampleBatchModal from "@/components/SampleBatchModal";
import PropostaPedidoModal from "@/components/PropostaPedidoModal";
import DirectOrderModal from "@/components/DirectOrderModal";
import ViewSwitcher from "@/components/ViewSwitcher";
import FilterBar, { applyFilters } from "@/components/FilterBar";
import ListView from "@/components/ListView";

function CRMSubNav({ active }) {
    const navigate = useNavigate();
    const tabs = [
        { id: "clients", label: "Clientes", path: "/crm/clients" },
        { id: "projects", label: "Projetos", path: "/crm/projects" },
        { id: "samples", label: "Amostras", path: "/crm/samples" },
        { id: "orders", label: "Pedidos", path: "/orders" },
    ];
    return (
        <div className="flex items-center gap-1 mb-5 border-b border-border pb-3">
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    onClick={() => navigate(tab.path)}
                    className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                        active === tab.id
                            ? "bg-primary text-primary-foreground shadow-sm"
                            : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    }`}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    );
}

const STAGES = [
    { id: "projeto_em_discussao", label: "Projeto em Discussão", color: "bg-violet-500" },
    { id: "amostra_solicitada", label: "Amostra Solicitada", color: "bg-emerald-500" },
    { id: "amostra_em_desenvolvimento", label: "Amostra em Desenvolvimento", color: "bg-blue-500" },
    { id: "amostra_enviada", label: "Amostra Enviada", color: "bg-cyan-500" },
    { id: "em_negociacao", label: "Em Negociação", color: "bg-amber-500" },
    { id: "pedido_aprovado", label: "Pedido Aprovado", color: "bg-lime-500" },
    { id: "projeto_arquivado", label: "Projeto Arquivado", color: "bg-slate-500" },
];

function formatSlugLabel(value) {
    if (!value) return "";
    const overrides = { anvisa: "ANVISA", ph: "pH" };
    return String(value)
        .split("_")
        .map((part) => overrides[part.toLowerCase()] || (part ? part[0].toUpperCase() + part.slice(1) : ""))
        .join(" ");
}

function createEmptySample() {
    return {
        nome_produto: "",
        categoria: "",
        briefing_base: "",
        responsavel_pd: "",
        parametro_variacao: "",
        tipo_amostra: "",
        referencia_formula: "",
        quantidade_por_variacao: "",
        unidade_quantidade: "g",
        prazo_entrega_cliente: "",
        briefing_especifico: "",
        feedback_cliente: "",
        direcoes_retrabalho: "",
        resultado: "",
        produto: "",
        objetivo_projeto: "",
        aplicacoes_desenvolver: "",
        ativos_claims: "",
        referencias: "",
        referencias_fotos: [],
        orcamento_projeto: "",
        textura_esperada: "",
        aplicacao: "",
        sensorial: "",
        ph: "",
        observacao_tecnica: "",
        variacoes: [{ descricao_aplicacao: "", percentual_fragrancia: "", referencia_fragrancia: "", custo_fragrancia: "", custo_fragrancia_currency: "USD", observacoes_especificas: "" }],
    };
}

function KickoffBadge({ project }) {
    if (!project?.kickoff_status) return null;
    const approved = project.kickoff_status === "aprovado";
    return (
        <Badge variant={approved ? "outline" : "secondary"} className="text-[10px]">
            {approved ? "Kickoff aprovado" : `Kickoff ${project.kickoff_status === "aguardando_aprovacao" ? "em aprovacao" : "pendente"}`}
        </Badge>
    );
}

export default function CRM2Page() {
    const navigate = useNavigate();
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filters, setFilters] = useState({});
    const [view, setView] = useState(() => localStorage.getItem("crm2:view") || "kanban");
    const [constants, setConstants] = useState(null);
    const [users, setUsers] = useState([]);
    const [selectedProjectId, setSelectedProjectId] = useState(null);
    const [selectedProjectData, setSelectedProjectData] = useState(null);
    const [showBatchSamples, setShowBatchSamples] = useState(false);
    const [batchProjectId, setBatchProjectId] = useState(null);
    const [batchSamples, setBatchSamples] = useState([createEmptySample()]);
    const [batchProjetoData, setBatchProjetoData] = useState(null);
    const [showPropostaPedido, setShowPropostaPedido] = useState(false);
    const [showDirectOrder, setShowDirectOrder] = useState(false);
    const [propostaProjeto, setPropostaProjeto] = useState(null);
    const [showArchiveDialog, setShowArchiveDialog] = useState(false);
    const [pendingArchiveProject, setPendingArchiveProject] = useState(null);
    const [archiveReason, setArchiveReason] = useState("");

    useEffect(() => {
        localStorage.setItem("crm2:view", view);
    }, [view]);

    const loadProjects = useCallback(async () => {
        try {
            const { data } = await api.get("/crm/projects");
            setProjects(Array.isArray(data) ? data.map((project) => ({
                ...project,
                stage: project.stage === "amostras" ? "amostra_solicitada" : project.stage,
            })) : []);
        } catch (error) {
            console.error("Failed to load projects", error);
            setProjects([]);
        } finally {
            setLoading(false);
        }
    }, []);

    const loadMetadata = useCallback(async () => {
        try {
            const [{ data: crmConstants }, { data: crmUsers }] = await Promise.all([
                api.get("/crm/constants"),
                api.get("/crm/users-list"),
            ]);
            setConstants(crmConstants);
            setUsers(crmUsers || []);
        } catch (error) {
            console.error("Failed to load CRM metadata", error);
        }
    }, []);

    const loadProjectDetail = useCallback(async (projectId) => {
        if (!projectId) return;
        try {
            const { data } = await api.get(`/crm/projects/${projectId}/full`);
            setSelectedProjectData({
                ...data,
                project: data?.project ? {
                    ...data.project,
                    stage: data.project.stage === "amostras" ? "amostra_solicitada" : data.project.stage,
                } : null,
            });
        } catch (error) {
            toast.error(formatApiError(error));
        }
    }, []);

    useEffect(() => { loadProjects(); }, [loadProjects]);
    useEffect(() => { loadMetadata(); }, [loadMetadata]);
    useEffect(() => { if (selectedProjectId) loadProjectDetail(selectedProjectId); }, [selectedProjectId, loadProjectDetail]);

    const stageLabelMap = useMemo(() => constants?.stage_labels || Object.fromEntries(STAGES.map((stage) => [stage.id, stage.label])), [constants]);

    const pdStatusLabel = {
        OPEN: "Aberto",
        IN_PROGRESS: "Em andamento",
        IN_TESTS: "Em testes",
        WAITING_APPROVAL: "Aguard. aprovação",
        APPROVED: "Aprovado",
        CLOSED: "Fechado",
    };
    const pdStatusColor = {
        OPEN: "bg-slate-100 text-slate-700 border-slate-200",
        IN_PROGRESS: "bg-blue-50 text-blue-700 border-blue-200",
        IN_TESTS: "bg-purple-50 text-purple-700 border-purple-200",
        WAITING_APPROVAL: "bg-amber-50 text-amber-700 border-amber-200",
        APPROVED: "bg-green-50 text-green-700 border-green-200",
        CLOSED: "bg-gray-100 text-gray-500 border-gray-200",
    };
    const projectPositioningOptions = useMemo(() => constants?.project_posicionamento || [], [constants]);
    const projectServiceOptions = useMemo(() => constants?.project_tipo_servico || [], [constants]);
    const projectRestrictionOptions = useMemo(() => constants?.project_restricoes_tecnicas || [], [constants]);
    const sampleConstants = useMemo(() => constants || {}, [constants]);
    // A4: mesma fonte de verdade do cliente (categoria_interesse) — sem lista própria.
    const projectCategoryOptions = useMemo(() => (
        Object.entries(constants?.categoria_interesse || {}).flatMap(([group, values]) =>
            (values || []).map((value) => ({ value, group, label: formatSlugLabel(value) }))
        )
    ), [constants]);

    // === Filter configuration ===
    const filterFields = useMemo(() => ([
        {
            key: "search",
            type: "search",
            placeholder: "Buscar por projeto, cliente ou conceito...",
            searchKeys: [
                (p) => p.nome_projeto,
                (p) => p.cliente_nome,
                (p) => p.ideia_conceito,
                (p) => p.referencia_mercado,
            ],
        },
        {
            key: "stage",
            type: "multi",
            label: "Fase",
            options: STAGES.map((s) => ({ value: s.id, label: s.label })),
            getter: (p) => p.stage,
        },
        {
            key: "categoria",
            type: "select",
            label: "Categoria",
            options: Array.from(new Set(projects.map((p) => p.categoria).filter(Boolean)))
                .map((v) => ({ value: v, label: formatSlugLabel(v) })),
            getter: (p) => p.categoria,
        },
        {
            key: "responsavel_comercial",
            type: "select",
            label: "Responsável",
            options: (users || []).map((u) => ({ value: u.id, label: u.name })),
            getter: (p) => p.responsavel_comercial,
        },
        {
            key: "tipo_servico",
            type: "select",
            label: "Tipo de serviço",
            options: projectServiceOptions.map((v) => ({ value: v, label: formatSlugLabel(v) })),
            getter: (p) => p.tipo_servico,
        },
    ]), [projects, users, projectServiceOptions]);

    const filteredProjects = useMemo(() => applyFilters(projects, filters, filterFields), [projects, filters, filterFields]);

    const projectsByStage = useMemo(() => STAGES.reduce((accumulator, stage) => {
        accumulator[stage.id] = filteredProjects.filter((project) => (project.stage || "") === stage.id);
        return accumulator;
    }, {}), [filteredProjects]);

    const projetoDataFromProject = (proj) => ({
        nome_projeto: proj?.nome_projeto || "",
        categoria: proj?.categoria || "",
        responsavel_comercial: proj?.responsavel_comercial || "",
        ideia_conceito: proj?.ideia_conceito || "",
        referencia_mercado: proj?.referencia_mercado || "",
        publico_alvo: proj?.publico_alvo || "",
        posicionamento: proj?.posicionamento || "",
        tipo_servico: proj?.tipo_servico || "",
        faixa_preco_venda: proj?.faixa_preco_venda ?? "",
        volume_estimado_pedido: proj?.volume_estimado_pedido ?? "",
        prazo_desejado_amostra: proj?.prazo_desejado_amostra || "",
        sensorial_desejado: proj?.sensorial_desejado || "",
        claims_desejados: proj?.claims_desejados || "",
        restricoes_tecnicas: proj?.restricoes_tecnicas || [],
        observacoes_livres: proj?.observacoes_livres || "",
    });

    const generateVariacaoLetters = (count) => {
        const letters = [];
        for (let index = 0; index < count; index += 1) {
            letters.push(indexToLetters(index));
        }
        return letters;
    };

    const addVariacao = (sampleIndex) => {
        const next = [...batchSamples];
        next[sampleIndex].variacoes.push({
            descricao_aplicacao: "",
            percentual_fragrancia: "",
            referencia_fragrancia: "",
            custo_fragrancia: "",
            custo_fragrancia_currency: "USD",
            observacoes_especificas: "",
        });
        setBatchSamples(next);
    };

    const removeVariacao = (sampleIndex, variacaoIndex) => {
        const next = [...batchSamples];
        if (next[sampleIndex].variacoes.length > 1) {
            next[sampleIndex].variacoes.splice(variacaoIndex, 1);
            setBatchSamples(next);
        }
    };

    const updateVariacao = (sampleIndex, variacaoIndex, field, value) => {
        const next = [...batchSamples];
        next[sampleIndex].variacoes[variacaoIndex][field] = value;
        setBatchSamples(next);
    };

    const handleMoveProject = async (projectId, stage, motivoArquivamento = "") => {
        const { data } = await api.put(`/crm/projects/${projectId}/move`, {
            stage,
            motivo_arquivamento: motivoArquivamento || undefined,
        });
        toast.success(`Projeto movido para ${data.to_stage}`);
        if (data.kickoff_criado?.kickoff_id) {
            toast.success(`Kickoff ${data.kickoff_criado.numero_kickoff} criado.`, {
                action: {
                    label: "Abrir",
                    onClick: () => navigate(`/kickoff/${data.kickoff_criado.kickoff_id}`),
                },
            });
        }
        if (data.trigger_batch_samples) {
            setBatchProjectId(projectId);
            const proj = projects.find(p => p.id === projectId);
            const inherited = createEmptySample();
            if (proj) {
                if (proj.categoria) inherited.categoria = proj.categoria;
                if (proj.responsavel_interno) inherited.responsavel_pd = proj.responsavel_interno;
            }
            setBatchProjetoData(projetoDataFromProject(proj));
            setBatchSamples([inherited]);
            setShowBatchSamples(true);
        }
        await loadProjects();
        if (selectedProjectId === projectId) {
            await loadProjectDetail(projectId);
        }
    };

    const handleReorder = async (clienteId) => {
        try {
            const { data } = await api.get(`/orders/reorder/${clienteId}`);
            navigate("/orders/new", { state: { draft: data } });
        } catch (e) {
            if (e.response?.status === 404) {
                toast.info("Nenhum pedido anterior encontrado. Criando novo pedido em branco.");
                navigate("/orders/new", { state: { clienteId } });
            } else {
                toast.error(formatApiError(e));
            }
        }
    };

    const handleResultadoCliente = async (sampleId, variacaoId, resultado) => {
        try {
            await api.post(`/crm/samples/${sampleId}/variacoes/${variacaoId}/resultado-cliente`, { resultado });
            toast.success(resultado === "aprovada" ? "Amostra aprovada pelo cliente!" : "Reprovação registrada.");
            await loadProjects();
            if (selectedProjectId) await loadProjectDetail(selectedProjectId);
        } catch (error) {
            toast.error(formatApiError(error));
        }
    };

    const handleDragEnd = async (result) => {
        if (!result.destination) return;
        const { draggableId, source, destination } = result;
        if (source.droppableId === destination.droppableId) return;

        if (destination.droppableId === "projeto_arquivado") {
            setPendingArchiveProject(draggableId);
            setArchiveReason("");
            setShowArchiveDialog(true);
            return;
        }

        try {
            await handleMoveProject(draggableId, destination.droppableId);
        } catch (error) {
            toast.error(formatApiError(error));
        }
    };

    const handleBatchSampleSubmit = async () => {
        if (!batchProjectId) return;
        const validSamples = batchSamples.filter((sample) => (
            sample.nome_produto.trim()
            && sample.tipo_amostra
            && sample.prazo_entrega_cliente
        ));
        if (!validSamples.length) {
            toast.error("Preencha os campos obrigatórios de pelo menos uma amostra.");
            return;
        }

        const missingReferencia = validSamples.find((sample) => (
            sample.tipo_amostra === "adaptacao_de_formula" && !String(sample.referencia_formula || "").trim()
        ));
        if (missingReferencia) {
            toast.error(`Referência de fórmula é obrigatória para adaptação de fórmula (amostra "${missingReferencia.nome_produto}").`);
            return;
        }

        try {
            const projetoUpdates = batchProjetoData ? {
                categoria: batchProjetoData.categoria,
                responsavel_comercial: batchProjetoData.responsavel_comercial,
                ideia_conceito: batchProjetoData.ideia_conceito,
                referencia_mercado: batchProjetoData.referencia_mercado,
                publico_alvo: batchProjetoData.publico_alvo,
                posicionamento: batchProjetoData.posicionamento,
                tipo_servico: batchProjetoData.tipo_servico,
                faixa_preco_venda: parsePriceInput(batchProjetoData.faixa_preco_venda),
                volume_estimado_pedido: parseVolumeInput(batchProjetoData.volume_estimado_pedido),
                prazo_desejado_amostra: batchProjetoData.prazo_desejado_amostra,
                sensorial_desejado: batchProjetoData.sensorial_desejado,
                claims_desejados: batchProjetoData.claims_desejados,
                restricoes_tecnicas: batchProjetoData.restricoes_tecnicas,
                observacoes_livres: batchProjetoData.observacoes_livres,
            } : undefined;
            const payload = {
                projeto_id: batchProjectId,
                samples: validSamples.map((sample) => ({
                    ...sample,
                    quantidade_por_variacao: sample.quantidade_por_variacao ? parseFloat(sample.quantidade_por_variacao) : null,
                    variacoes: (sample.variacoes || []).map((variacao) => ({
                        ...variacao,
                        percentual_fragrancia: variacao.percentual_fragrancia ? parseFloat(variacao.percentual_fragrancia) : null,
                        custo_fragrancia: variacao.custo_fragrancia ? parseFloat(variacao.custo_fragrancia) : null,
                    })),
                })),
                projeto_updates: projetoUpdates,
            };
            const { data } = await api.post("/crm/samples/batch/v2", payload);
            toast.success(`${data.count} amostra(s) criada(s)!`);
            setShowBatchSamples(false);
            setBatchProjectId(null);
            setBatchSamples([createEmptySample()]);
            setBatchProjetoData(null);
            await loadProjects();
            if (selectedProjectId) {
                await loadProjectDetail(selectedProjectId);
            }
        } catch (error) {
            toast.error(formatApiError(error));
        }
    };

    const handleUpdateProject = async (projectId, updates) => {
        try {
            await api.put(`/crm/projects/${projectId}`, updates);
            toast.success("Projeto atualizado.");
            await loadProjects();
            if (selectedProjectId === projectId) {
                await loadProjectDetail(projectId);
            }
        } catch (error) {
            toast.error(formatApiError(error));
        }
    };

    const handleManualSampleCreation = () => {
        if (!selectedProjectId) return;
        setBatchProjectId(selectedProjectId);
        const inherited = createEmptySample();
        if (selectedProject) {
            if (selectedProject.categoria) inherited.categoria = selectedProject.categoria;
            if (selectedProject.responsavel_interno) inherited.responsavel_pd = selectedProject.responsavel_interno;
        }
        setBatchProjetoData(projetoDataFromProject(selectedProject));
        setBatchSamples([inherited]);
        setShowBatchSamples(true);
    };

    const confirmArchive = async () => {
        if (!pendingArchiveProject || !archiveReason.trim()) return;
        try {
            await handleMoveProject(pendingArchiveProject, "projeto_arquivado", archiveReason);
            setShowArchiveDialog(false);
            setPendingArchiveProject(null);
            setArchiveReason("");
        } catch (error) {
            toast.error(formatApiError(error));
        }
    };

    const selectedProject = selectedProjectData?.project || projects.find((project) => project.id === selectedProjectId) || null;

    // A6/A7: máscara pt-BR (moeda / milhar) nos campos de edição do projeto — sincroniza
    // o texto exibido sempre que o projeto selecionado muda ou é recarregado.
    const [faixaPrecoDisplay, setFaixaPrecoDisplay] = useState("");
    const [volumeEstimadoDisplay, setVolumeEstimadoDisplay] = useState("");
    useEffect(() => {
        setFaixaPrecoDisplay(fmtPriceDisplay(selectedProject?.faixa_preco_venda ?? ""));
        setVolumeEstimadoDisplay(fmtVolumeDisplay(selectedProject?.volume_estimado_pedido ?? ""));
    }, [selectedProject?.id, selectedProject?.faixa_preco_venda, selectedProject?.volume_estimado_pedido]);

    if (loading) {
        return (
            <div className="p-8 page-enter">
                <div className="animate-pulse space-y-4">
                    <div className="h-8 w-64 bg-muted rounded" />
                    <div className="flex gap-4">{[1, 2, 3].map((item) => <div key={item} className="h-96 flex-1 bg-muted rounded-lg" />)}</div>
                </div>
            </div>
        );
    }

    const userNameById = Object.fromEntries((users || []).map((u) => [u.id, u.name]));

    return (
        <div className="p-6 page-enter" data-testid="crm2-page">
            <CRMSubNav active="projects" />
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h1 className="text-3xl font-heading font-semibold tracking-tight">Pipeline de Projetos</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        {filteredProjects.length} de {projects.length} projetos
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Button variant="outline" onClick={() => setShowDirectOrder(true)}>
                        <ShoppingCart className="h-4 w-4 mr-2" /> Pedido Direto
                    </Button>
                    <ViewSwitcher value={view} onChange={setView} testIdPrefix="crm2" />
                </div>
            </div>

            <DirectOrderModal
                open={showDirectOrder}
                onOpenChange={setShowDirectOrder}
                onCreated={(order) => navigate(`/orders/${order.id}`)}
            />

            <FilterBar
                filters={filters}
                onChange={setFilters}
                fields={filterFields}
                testIdPrefix="crm2-filter"
            />

            {view === "kanban" ? (
                <DragDropContext onDragEnd={handleDragEnd}>
                    <div className="flex gap-4 overflow-x-auto pb-2" data-testid="crm2-kanban">
                        {STAGES.map((stage) => (
                            <Droppable droppableId={stage.id} key={stage.id}>
                                {(provided, snapshot) => (
                                    <div
                                        ref={provided.innerRef}
                                        {...provided.droppableProps}
                                        className={`min-w-[320px] rounded-lg border border-border/60 ${snapshot.isDraggingOver ? "bg-accent/50" : "bg-muted/30"}`}
                                    >
                                        <div className="p-3 border-b border-border">
                                            <div className="flex items-center gap-2">
                                                <div className={`w-2 h-2 rounded-full ${stage.color}`} />
                                                <h3 className="font-heading font-medium text-sm">{stage.label}</h3>
                                                <span className="text-xs text-muted-foreground mono-num ml-auto">
                                                    {(projectsByStage[stage.id] || []).length}
                                                </span>
                                            </div>
                                        </div>
                                        <div className="p-2 space-y-2 min-h-[420px]">
                                            {(projectsByStage[stage.id] || []).map((project, index) => (
                                                <Draggable draggableId={project.id} index={index} key={project.id}>
                                                    {(draggableProvided, dragSnapshot) => (
                                                        <div
                                                            ref={draggableProvided.innerRef}
                                                            {...draggableProvided.draggableProps}
                                                            className={`bg-card border border-border rounded-md p-3 cursor-pointer transition-transform duration-150 ${
                                                                dragSnapshot.isDragging ? "kanban-card-dragging" : "hover:-translate-y-0.5 hover:shadow-sm"
                                                            }`}
                                                            onClick={() => setSelectedProjectId(project.id)}
                                                        >
                                                            <div className="flex items-start justify-between gap-2">
                                                                <div className="min-w-0">
                                                                    <p className="font-medium text-sm truncate">{project.nome_projeto}</p>
                                                                    <p className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                                                                        <Building2 className="h-3 w-3" />
                                                                        {project.cliente_nome}
                                                                    </p>
                                                                    {project.ideia_conceito && (
                                                                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{project.ideia_conceito}</p>
                                                                    )}
                                                                </div>
                                                                <div {...draggableProvided.dragHandleProps}>
                                                                    <GripVertical className="h-4 w-4 text-muted-foreground/50" />
                                                                </div>
                                                            </div>
                                                            <div className="mt-2 flex flex-wrap items-center gap-2">
                                                                {project.categoria && (
                                                                    <Badge variant="outline" className="text-[10px]">
                                                                        {formatSlugLabel(project.categoria)}
                                                                    </Badge>
                                                                )}
                                                                {project.posicionamento && (
                                                                    <Badge variant="secondary" className="text-[10px]">
                                                                        {formatSlugLabel(project.posicionamento)}
                                                                    </Badge>
                                                                )}
                                                                <KickoffBadge project={project} />
                                                                {project.prazo_desejado_amostra && (
                                                                    <span className="text-[10px] text-muted-foreground ml-auto">
                                                                        {new Date(project.prazo_desejado_amostra).toLocaleDateString("pt-BR")}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            {project.stage === "amostra_enviada" && (
                                                                <div className="mt-2 pt-2 border-t border-border">
                                                                    <button
                                                                        className="w-full flex items-center justify-center gap-1.5 text-xs text-cyan-700 font-medium py-1 rounded hover:bg-cyan-50 transition-colors"
                                                                        onClick={(e) => { e.stopPropagation(); setSelectedProjectId(project.id); }}
                                                                    >
                                                                        <CheckCircle className="h-3.5 w-3.5" /> Registrar aprovação do cliente
                                                                    </button>
                                                                </div>
                                                            )}
                                                            {project.stage === "em_negociacao" && (
                                                                <div className="mt-2 pt-2 border-t border-border">
                                                                    <Button
                                                                        size="sm"
                                                                        variant="outline"
                                                                        className="w-full gap-1.5 text-xs text-amber-700 border-amber-300 hover:bg-amber-50"
                                                                        onClick={(e) => { e.stopPropagation(); setPropostaProjeto(project); setShowPropostaPedido(true); }}
                                                                    >
                                                                        <ShoppingCart className="h-3.5 w-3.5" /> Proposta & Pedido
                                                                    </Button>
                                                                </div>
                                                            )}
                                                            {project.stage === "pedido_aprovado" && project.cliente_id && (
                                                                <div className="mt-2 pt-2 border-t border-border">
                                                                    <Button
                                                                        size="sm"
                                                                        variant="outline"
                                                                        className="w-full gap-1.5 text-xs text-emerald-700 border-emerald-300 hover:bg-emerald-50"
                                                                        onClick={(e) => { e.stopPropagation(); handleReorder(project.cliente_id); }}
                                                                    >
                                                                        <ShoppingCart className="h-3.5 w-3.5" /> Nova Reposição
                                                                    </Button>
                                                                </div>
                                                            )}
                                                        </div>
                                                    )}
                                                </Draggable>
                                            ))}
                                            {provided.placeholder}
                                        </div>
                                    </div>
                                )}
                            </Droppable>
                        ))}
                    </div>
                </DragDropContext>
            ) : (
                <ListView
                    items={filteredProjects}
                    onRowClick={(p) => setSelectedProjectId(p.id)}
                    emptyMessage="Nenhum projeto corresponde aos filtros."
                    testIdPrefix="crm2-list"
                    columns={[
                        { key: "nome_projeto", label: "Projeto",
                          render: (p) => <span className="font-medium">{p.nome_projeto}</span> },
                        { key: "cliente_nome", label: "Cliente" },
                        { key: "categoria", label: "Categoria",
                          render: (p) => p.categoria ? formatSlugLabel(p.categoria) : "—" },
                        { key: "tipo_servico", label: "Tipo de serviço",
                          render: (p) => p.tipo_servico ? formatSlugLabel(p.tipo_servico) : "—" },
                        { key: "stage", label: "Fase",
                          render: (p) => (
                              <div className="flex items-center gap-2 flex-wrap">
                                  <Badge variant="outline" className="text-[10px]">
                                      {stageLabelMap[p.stage] || p.stage}
                                  </Badge>
                                  <KickoffBadge project={p} />
                              </div>
                          ) },
                        { key: "responsavel_comercial", label: "Responsável",
                          render: (p) => userNameById[p.responsavel_comercial] || "—" },
                        { key: "prazo_desejado_amostra", label: "Prazo amostra",
                          render: (p) => p.prazo_desejado_amostra ? new Date(p.prazo_desejado_amostra).toLocaleDateString("pt-BR") : "—" },
                    ]}
                />
            )}

            <Sheet
                open={!!selectedProjectId}
                onOpenChange={(open) => {
                    if (!open) {
                        setSelectedProjectId(null);
                        setSelectedProjectData(null);
                    }
                }}
            >
                <SheetContent className="w-[560px] sm:w-[640px] p-0 flex flex-col" side="right">
                    {selectedProject && (
                        <>
                            <SheetHeader className="p-6 pb-3">
                                <SheetTitle className="font-heading text-xl">{selectedProject.nome_projeto}</SheetTitle>
                                <div className="flex flex-wrap items-center gap-2 mt-1">
                                    <Badge variant="outline">{selectedProject.cliente_nome}</Badge>
                                    <Badge>{stageLabelMap[selectedProject.stage] || selectedProject.stage}</Badge>
                                    <KickoffBadge project={selectedProject} />
                                    {selectedProject.categoria && (
                                        <Badge variant="secondary">{formatSlugLabel(selectedProject.categoria)}</Badge>
                                    )}
                                </div>
                            </SheetHeader>
                            <Separator />
                            <div className="flex-1 overflow-y-auto p-6 space-y-5">
                                <section className="space-y-3">
                                    <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Pré-briefing</h4>
                                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Nome do projeto</Label>
                                            <Input
                                                defaultValue={selectedProject.nome_projeto || ""}
                                                onBlur={(event) => { if (event.target.value !== selectedProject.nome_projeto) handleUpdateProject(selectedProject.id, { nome_projeto: event.target.value }); }}
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Categoria</Label>
                                            <Select
                                                value={selectedProject.categoria || ""}
                                                onValueChange={(value) => handleUpdateProject(selectedProject.id, { categoria: value })}
                                            >
                                                <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                                <SelectContent>
                                                    {projectCategoryOptions.map((option) => (
                                                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Responsável comercial</Label>
                                            <Select
                                                value={selectedProject.responsavel_comercial || ""}
                                                onValueChange={(value) => handleUpdateProject(selectedProject.id, { responsavel_comercial: value })}
                                            >
                                                <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                                <SelectContent>
                                                    {users.map((user) => (
                                                        <SelectItem key={user.id} value={user.id}>{user.name}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Ideia / conceito</Label>
                                            <Textarea
                                                defaultValue={selectedProject.ideia_conceito || ""}
                                                rows={3}
                                                onBlur={(event) => { if (event.target.value !== selectedProject.ideia_conceito) handleUpdateProject(selectedProject.id, { ideia_conceito: event.target.value, briefing_tecnico: event.target.value }); }}
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Referência de mercado</Label>
                                            <Input
                                                defaultValue={selectedProject.referencia_mercado || ""}
                                                onBlur={(event) => { if (event.target.value !== selectedProject.referencia_mercado) handleUpdateProject(selectedProject.id, { referencia_mercado: event.target.value }); }}
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Público-alvo</Label>
                                            <Input
                                                defaultValue={selectedProject.publico_alvo || ""}
                                                onBlur={(event) => { if (event.target.value !== selectedProject.publico_alvo) handleUpdateProject(selectedProject.id, { publico_alvo: event.target.value }); }}
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Posicionamento</Label>
                                            <Select
                                                value={selectedProject.posicionamento || ""}
                                                onValueChange={(value) => handleUpdateProject(selectedProject.id, { posicionamento: value })}
                                            >
                                                <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                                <SelectContent>
                                                    {projectPositioningOptions.map((option) => (
                                                        <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Tipo de serviço</Label>
                                            <Select
                                                value={selectedProject.tipo_servico || ""}
                                                onValueChange={(value) => handleUpdateProject(selectedProject.id, { tipo_servico: value })}
                                            >
                                                <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                                <SelectContent>
                                                    {projectServiceOptions.map((option) => (
                                                        <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Faixa de preço de venda (R$)</Label>
                                            <Input
                                                type="text"
                                                inputMode="decimal"
                                                placeholder={DEFAULT_PRICE_DISPLAY}
                                                value={faixaPrecoDisplay}
                                                onChange={(event) => setFaixaPrecoDisplay(event.target.value)}
                                                onFocus={() => setFaixaPrecoDisplay((current) => seedPriceDisplay(current))}
                                                onBlur={(event) => {
                                                    const formatted = fmtPriceDisplay(event.target.value);
                                                    setFaixaPrecoDisplay(formatted);
                                                    handleUpdateProject(selectedProject.id, { faixa_preco_venda: parsePriceInput(event.target.value) });
                                                }}
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Volume estimado por pedido</Label>
                                            <Input
                                                type="text"
                                                inputMode="numeric"
                                                placeholder={DEFAULT_VOLUME_DISPLAY}
                                                value={volumeEstimadoDisplay}
                                                onChange={(event) => setVolumeEstimadoDisplay(event.target.value)}
                                                onFocus={() => setVolumeEstimadoDisplay((current) => seedVolumeDisplay(current))}
                                                onBlur={(event) => {
                                                    const formatted = fmtVolumeDisplay(event.target.value);
                                                    setVolumeEstimadoDisplay(formatted);
                                                    handleUpdateProject(selectedProject.id, { volume_estimado_pedido: parseVolumeInput(event.target.value) });
                                                }}
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Prazo desejado para amostra</Label>
                                            <Input
                                                type="date"
                                                defaultValue={selectedProject.prazo_desejado_amostra || ""}
                                                onBlur={(event) => handleUpdateProject(selectedProject.id, { prazo_desejado_amostra: event.target.value, prazo_prometido_cliente: event.target.value })}
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Sensorial desejado</Label>
                                            <Input
                                                defaultValue={selectedProject.sensorial_desejado || ""}
                                                onBlur={(event) => { if (event.target.value !== selectedProject.sensorial_desejado) handleUpdateProject(selectedProject.id, { sensorial_desejado: event.target.value }); }}
                                            />
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Claims desejados</Label>
                                            <Textarea
                                                defaultValue={selectedProject.claims_desejados || ""}
                                                rows={2}
                                                onBlur={(event) => { if (event.target.value !== selectedProject.claims_desejados) handleUpdateProject(selectedProject.id, { claims_desejados: event.target.value }); }}
                                            />
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Restrições técnicas</Label>
                                            <div className="flex flex-wrap gap-2">
                                                {projectRestrictionOptions.map((option) => {
                                                    const active = (selectedProject.restricoes_tecnicas || []).includes(option);
                                                    return (
                                                        <button
                                                            key={option}
                                                            type="button"
                                                            className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${active ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:bg-accent"}`}
                                                            onClick={() => {
                                                                const current = selectedProject.restricoes_tecnicas || [];
                                                                const next = current.includes(option)
                                                                    ? current.filter((item) => item !== option)
                                                                    : [...current, option];
                                                                handleUpdateProject(selectedProject.id, { restricoes_tecnicas: next });
                                                            }}
                                                        >
                                                            {formatSlugLabel(option)}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Observações livres</Label>
                                            <Textarea
                                                defaultValue={selectedProject.observacoes_livres || ""}
                                                rows={2}
                                                onBlur={(event) => { if (event.target.value !== selectedProject.observacoes_livres) handleUpdateProject(selectedProject.id, { observacoes_livres: event.target.value }); }}
                                            />
                                        </div>
                                    </div>
                                </section>

                                <Separator />

                                <section className="space-y-3">
                                    <div className="flex items-center justify-between">
                                        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Histórico de amostras</h4>
                                        <Button size="sm" onClick={handleManualSampleCreation}>
                                            <PackagePlus className="h-4 w-4 mr-1" /> Criar amostras
                                        </Button>
                                    </div>
                                    {(selectedProjectData?.samples || []).length === 0 && (
                                        <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
                                            Nenhuma amostra vinculada a este projeto.
                                        </div>
                                    )}
                                    {(selectedProjectData?.samples || []).map((sample) => (
                                        <div key={sample.id} className="rounded-lg border border-border p-4 space-y-3">
                                            <div className="flex items-center justify-between">
                                                <div>
                                                    <p className="font-medium">{sample.nome_produto || sample.nome_amostra || "Amostra"}</p>
                                                    <p className="text-xs text-muted-foreground">
                                                        #{sample.numero_amostra} · {sample.prazo_entrega_cliente ? new Date(sample.prazo_entrega_cliente).toLocaleDateString("pt-BR") : "sem prazo"}
                                                    </p>
                                                </div>
                                                <Badge variant="outline">{stageLabelMap[sample.stage] || sample.stage}</Badge>
                                            </div>
                                            <div className="space-y-2">
                                                {(sample.variacoes || []).map((variacao) => (
                                                    <div key={variacao.id} className="rounded-md bg-muted/40 px-3 py-2">
                                                        <div className="flex items-start justify-between gap-3">
                                                            <div className="flex-1 min-w-0">
                                                                <p className="text-sm font-medium">{variacao.codigo}</p>
                                                                <p className="text-xs text-muted-foreground">{variacao.descricao_aplicacao || "Sem descrição"}</p>
                                                                {variacao.feedback_cliente && (
                                                                    <p className="text-xs text-muted-foreground mt-1">Feedback: {variacao.feedback_cliente}</p>
                                                                )}
                                                                {variacao.pd_status && (
                                                                    <div className="flex items-center gap-1.5 mt-1.5">
                                                                        <FlaskConical className="h-3 w-3 text-muted-foreground shrink-0" />
                                                                        <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded border ${pdStatusColor[variacao.pd_status] || "bg-muted text-muted-foreground"}`}>
                                                                            P&D: {pdStatusLabel[variacao.pd_status] || variacao.pd_status}
                                                                        </span>
                                                                        {variacao.pd_request_id && (
                                                                            <button
                                                                                className="text-[10px] text-primary underline underline-offset-2 flex items-center gap-0.5 hover:opacity-70"
                                                                                onClick={() => navigate(`/pd/requests/${variacao.pd_request_id}`)}
                                                                            >
                                                                                ver <ExternalLink className="h-2.5 w-2.5" />
                                                                            </button>
                                                                        )}
                                                                    </div>
                                                                )}
                                                            </div>
                                                            <div className="text-right shrink-0">
                                                                <Badge variant="secondary" className="text-[10px]">{stageLabelMap[variacao.status] || variacao.status}</Badge>
                                                                {(variacao.resultado || sample.resultado) && (
                                                                    <p className="text-[10px] text-muted-foreground mt-1">
                                                                        Resultado: {formatSlugLabel(variacao.resultado || sample.resultado)}
                                                                    </p>
                                                                )}
                                                            </div>
                                                        </div>
                                                        {selectedProject?.stage === "amostra_enviada" && !variacao.aprovacao_externa && variacao.resultado !== "aprovada" && variacao.resultado !== "reprovada" && (
                                                            <div className="mt-2 flex gap-2">
                                                                <Button
                                                                    size="sm"
                                                                    variant="outline"
                                                                    className="flex-1 gap-1.5 text-xs text-emerald-700 border-emerald-300 hover:bg-emerald-50"
                                                                    onClick={() => handleResultadoCliente(sample.id, variacao.id, "aprovada")}
                                                                >
                                                                    <CheckCircle className="h-3.5 w-3.5" /> Cliente aprovou
                                                                </Button>
                                                                <Button
                                                                    size="sm"
                                                                    variant="outline"
                                                                    className="flex-1 gap-1.5 text-xs text-red-700 border-red-300 hover:bg-red-50"
                                                                    onClick={() => handleResultadoCliente(sample.id, variacao.id, "reprovada")}
                                                                >
                                                                    <XCircle className="h-3.5 w-3.5" /> Cliente reprovou
                                                                </Button>
                                                            </div>
                                                        )}
                                                        {(variacao.aprovacao_externa || variacao.resultado === "aprovada") && (
                                                            <div className="mt-1.5 flex items-center gap-1 text-[10px] text-emerald-700 font-medium">
                                                                <CheckCircle className="h-3 w-3" /> Aprovado pelo cliente
                                                            </div>
                                                        )}
                                                        {variacao.resultado === "reprovada" && (
                                                            <div className="mt-1.5 flex items-center gap-1 text-[10px] text-red-700 font-medium">
                                                                <XCircle className="h-3 w-3" /> Reprovado pelo cliente
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    ))}
                                </section>

                                <Separator />

                                <section className="space-y-3">
                                    <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Histórico de movimentações</h4>
                                    {(selectedProject.historico_movimentacoes || []).slice().reverse().map((movement, index) => (
                                        <div key={index} className="flex gap-3 items-start">
                                            <div className="mt-1 w-2 h-2 rounded-full bg-primary shrink-0" />
                                            <div>
                                                <p className="text-sm">
                                                    <span className="font-medium">{stageLabelMap[movement.de] || movement.de}</span>
                                                    <ChevronRight className="h-3 w-3 inline mx-1" />
                                                    <span className="font-medium">{stageLabelMap[movement.para] || movement.para}</span>
                                                </p>
                                                <p className="text-xs text-muted-foreground">
                                                    {movement.usuario} · {new Date(movement.data).toLocaleString("pt-BR")}
                                                </p>
                                            </div>
                                        </div>
                                    ))}
                                    {selectedProject.motivo_arquivamento && (
                                        <div className="rounded-md border border-border bg-muted/30 p-3 text-sm">
                                            <span className="font-medium">Motivo do arquivamento:</span> {selectedProject.motivo_arquivamento}
                                        </div>
                                    )}
                                </section>
                            </div>

                            <div className="border-t p-4">
                                <Button
                                    variant="outline"
                                    className="w-full justify-start text-muted-foreground"
                                    onClick={() => {
                                        setPendingArchiveProject(selectedProject.id);
                                        setArchiveReason(selectedProject.motivo_arquivamento || "");
                                        setShowArchiveDialog(true);
                                    }}
                                >
                                    <Archive className="h-4 w-4 mr-2" />
                                    Arquivar projeto
                                </Button>
                            </div>
                        </>
                    )}
                </SheetContent>
            </Sheet>

            <SampleBatchModal
                open={showBatchSamples}
                onOpenChange={(open) => {
                    setShowBatchSamples(open);
                    if (!open) {
                        setBatchProjectId(null);
                        setBatchSamples([createEmptySample()]);
                        setBatchProjetoData(null);
                    }
                }}
                batchSamples={batchSamples}
                setBatchSamples={setBatchSamples}
                projetoData={batchProjetoData}
                onProjetoDataChange={setBatchProjetoData}
                onSubmit={handleBatchSampleSubmit}
                addVariacao={addVariacao}
                removeVariacao={removeVariacao}
                updateVariacao={updateVariacao}
                generateVariacaoLetters={generateVariacaoLetters}
                constants={sampleConstants}
                onAddSample={() => {
                    const proj = projects.find(p => p.id === batchProjectId);
                    const inherited = createEmptySample();
                    if (proj) {
                        if (proj.categoria) inherited.categoria = proj.categoria;
                        if (proj.responsavel_interno) inherited.responsavel_pd = proj.responsavel_interno;
                    }
                    setBatchSamples([...batchSamples, inherited]);
                }}
            />

            <PropostaPedidoModal
                open={showPropostaPedido}
                onOpenChange={(open) => {
                    setShowPropostaPedido(open);
                    if (!open) setPropostaProjeto(null);
                }}
                projeto={propostaProjeto}
                onSaved={() => {
                    toast.success("Proposta salva.");
                    loadProjects();
                }}
            />

            <Dialog open={showArchiveDialog} onOpenChange={setShowArchiveDialog}>
                <DialogContent className="max-w-md">
                    <DialogHeader>
                        <DialogTitle className="font-heading">Arquivar Projeto</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-3">
                        <Label>Motivo do arquivamento *</Label>
                        <Textarea value={archiveReason} onChange={(event) => setArchiveReason(event.target.value)} rows={4} />
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => { setShowArchiveDialog(false); setPendingArchiveProject(null); setArchiveReason(""); }}>
                            Cancelar
                        </Button>
                        <Button onClick={confirmArchive} disabled={!archiveReason.trim()}>
                            Arquivar
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
