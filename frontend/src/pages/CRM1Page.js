import { useState, useEffect, useCallback, useMemo } from "react";
import api from "@/lib/api";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter
} from "@/components/ui/dialog";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Plus, GripVertical, User, Trash2, Search, ChevronRight, AlertTriangle, Tag } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import ViewSwitcher from "@/components/ViewSwitcher";
import FilterBar, { applyFilters } from "@/components/FilterBar";
import ListView from "@/components/ListView";
import { formatApiError } from "@/lib/formatError";
import { CurrencyInput, fmtCurrency } from "@/components/ui/CurrencyInput";
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
import { Cli4Field } from "@/components/Cli4Field";

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
            {tabs.map(t => (
                <button
                    key={t.id}
                    onClick={() => navigate(t.path)}
                    className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                        active === t.id
                            ? "bg-primary text-primary-foreground shadow-sm"
                            : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    }`}
                >
                    {t.label}
                </button>
            ))}
        </div>
    );
}

const STAGES = [
    { id: "prospeccao", label: "Prospecção", color: "bg-blue-500" },
    { id: "qualificado", label: "Qualificado", color: "bg-cyan-500" },
    { id: "projeto_em_discussao", label: "Projeto em Discussão", color: "bg-violet-500" },
    { id: "negociacao", label: "Negociação", color: "bg-amber-500" },
    { id: "cliente_fechado", label: "Cliente Fechado", color: "bg-emerald-500" },
    { id: "cliente_perdido", label: "Cliente Perdido", color: "bg-red-500" },
];

// Espelha CLIENT_QUALIFICATION_REQUIRED_FIELDS (backend/crm_routes.py) só para exibição —
// a lista de QUAIS campos faltam vem sempre do backend (missing_qualification_fields).
const QUALIFICATION_FIELD_LABELS = {
    canal_origem: "Canal de origem",
    categoria_interesse: "Categoria de interesse",
    temperatura_lead: "Temperatura",
    responsavel_comercial: "Responsável comercial",
    segmento: "Segmento",
    "contato_principal.nome": "Contato — nome",
    "contato_principal.whatsapp": "Contato — WhatsApp",
};

Object.assign(QUALIFICATION_FIELD_LABELS, {
    decisores: "Decisores",
    tem_anvisa: "ANVISA",
    volume_estimado_mensal: "Volume estimado mensal",
    fornecedor_atual: "Fornecedor atual",
});

const LOSS_REASON_OPTIONS = [
    { value: "preco", label: "Preço" },
    { value: "prazo", label: "Prazo" },
    { value: "qualidade", label: "Qualidade" },
    { value: "concorrencia", label: "Concorrência" },
    { value: "projeto_cancelado", label: "Projeto Cancelado" },
    { value: "sem_retorno", label: "Sem Retorno" },
    { value: "outro", label: "Outro" },
];

const VOLUME_OPTIONS = [
    { value: "menos_1k", label: "< 1.000 un" },
    { value: "1k_5k", label: "1.000 - 5.000" },
    { value: "5k_20k", label: "5.000 - 20.000" },
    { value: "20k_50k", label: "20.000 - 50.000" },
    { value: "50k_100k", label: "50.000 - 100.000" },
    { value: "mais_100k", label: "> 100.000" },
];

const ANVISA_OPTIONS = [
    { value: "sim", label: "Sim" },
    { value: "nao", label: "Não" },
    { value: "depende", label: "Depende de Nós" },
];

function normalizeTemAnvisaValue(value) {
    if (!value) return "";
    return value === "depende_de_nos" ? "depende" : value;
}

const STAGE_ORDER = ["prospeccao", "qualificado", "projeto_em_discussao", "negociacao", "cliente_fechado", "cliente_perdido"];

const CANAL_GROUP_LABELS = {
    prospeccao_ativa_digital: "Prospecção Ativa — Digital",
    prospeccao_ativa_presencial: "Prospecção Ativa — Presencial",
    indicacao: "Indicação",
    inbound_digital: "Inbound — Digital",
    inbound_conteudo: "Inbound — Conteúdo",
    relacionamento_existente: "Relacionamento Existente",
    outros: "Outros",
};

const EMPTY_ADDITIONAL_CONTACT = { nome: "", cargo: "", cargo_custom: "", whatsapp: "", email: "" };

function hasMeaningfulContactData(contact) {
    if (!contact) return false;
    return Object.values(contact).some((value) => String(value || "").trim());
}

function hasNamedDecisionMaker(items = []) {
    return (items || []).some((item) => String(item?.nome || "").trim());
}

function getMissingProjectGateFields(client) {
    if (!client) return [];
    const contact = client.contato_principal || {};
    const missing = [];

    if (!client.canal_origem) missing.push("canal_origem");
    if (!Array.isArray(client.categoria_interesse) || client.categoria_interesse.length === 0) missing.push("categoria_interesse");
    if (!client.temperatura_lead) missing.push("temperatura_lead");
    if (!client.responsavel_comercial) missing.push("responsavel_comercial");
    if (!client.segmento) missing.push("segmento");
    if (!String(contact.nome || "").trim()) missing.push("contato_principal.nome");
    if (!String(contact.whatsapp || "").trim()) missing.push("contato_principal.whatsapp");
    if (!hasNamedDecisionMaker(client.decisores)) missing.push("decisores");
    if (!String(normalizeTemAnvisaValue(client.tem_anvisa) || "").trim()) missing.push("tem_anvisa");
    if (!String(client.volume_estimado_mensal || "").trim()) missing.push("volume_estimado_mensal");
    if (!client.fornecedor_atual || typeof client.fornecedor_atual !== "object" || !Object.prototype.hasOwnProperty.call(client.fornecedor_atual, "tem")) {
        missing.push("fornecedor_atual");
    }

    return [...new Set(missing)];
}

function createEmptyClient(defaultOwner = "") {
    return {
        nome_empresa: "",
        cnpj: "",
        contato_principal: { nome: "", cargo: "", cargo_custom: "", whatsapp: "", email: "" },
        contatos_adicionais: [],
        canal_origem: "",
        categoria_interesse: [],
        origem_lead: "",
        temperatura_lead: "morno",
        responsavel_comercial: defaultOwner,
        segmento: "",
        porte: "",
        regiao: "",
        site: "",
        instagram: "",
        observacoes: "",
        cli3: "",
        cli4: "",
        // Qualificação — pré-preencher para desbloquear avanço automático
        tem_anvisa: "",
        volume_estimado_mensal: "",
        fornecedor_atual: { tem: false, motivo_troca: "" },
        decisores: [{ nome: "", cargo: "", contato: "" }],
    };
}

function createEmptyProject(defaults = {}) {
    return {
        nome_projeto: "",
        categoria: "",
        responsavel_comercial: defaults.responsavel_comercial || "",
        briefing_resumido: "",
        ideia_conceito: "",
        referencia_mercado: "",
        publico_alvo: "",
        posicionamento: "",
        faixa_preco_venda: "",
        volume_estimado_pedido: "",
        tipo_servico: "",
        sensorial_desejado: "",
        restricoes_tecnicas: [],
        claims_desejados: "",
        prazo_desejado_amostra: "",
        observacoes_livres: "",
        ...defaults,
    };
}

function buildQualificationDraft(client) {
    return {
        id: client?.id || "",
        nome_empresa: client?.nome_empresa || "",
        contato_principal: {
            nome: client?.contato_principal?.nome || "",
            cargo: client?.contato_principal?.cargo || "",
            cargo_custom: client?.contato_principal?.cargo_custom || "",
            whatsapp: client?.contato_principal?.whatsapp || "",
            email: client?.contato_principal?.email || "",
        },
        canal_origem: client?.canal_origem || "",
        categoria_interesse: Array.isArray(client?.categoria_interesse) ? client.categoria_interesse : [],
        temperatura_lead: client?.temperatura_lead || "morno",
        responsavel_comercial: client?.responsavel_comercial || "",
        segmento: client?.segmento || "",
        tem_anvisa: normalizeTemAnvisaValue(client?.tem_anvisa),
        volume_estimado_mensal: client?.volume_estimado_mensal || "",
        decisores: Array.isArray(client?.decisores) && client.decisores.length > 0 ? client.decisores : [{ nome: "", cargo: "", contato: "" }],
        fornecedor_atual: client?.fornecedor_atual && typeof client.fornecedor_atual === "object"
            ? { tem: Boolean(client.fornecedor_atual.tem), motivo_troca: client.fornecedor_atual.motivo_troca || "" }
            : { tem: false, motivo_troca: "" },
    };
}

function formatSlugLabel(value) {
    if (!value) return "";
    const overrides = {
        ceo: "CEO",
        seo: "SEO",
        dm: "DM",
        pdv: "PDV",
        anvisa: "ANVISA",
        moq: "MOQ",
        bb: "BB",
        cc: "CC",
        ph: "pH",
        fps6: "FPS >= 6",
        edp: "Eau de Parfum",
    };

    return String(value)
        .split("_")
        .map((part) => overrides[part.toLowerCase()] || (part ? part[0].toUpperCase() + part.slice(1) : ""))
        .join(" ");
}

function flattenUniqueOptions(groups = {}, flatOptions = []) {
    const groupedValues = Object.values(groups || {}).flatMap((values) => values || []);
    return Array.from(new Set([...(groupedValues || []), ...(flatOptions || [])])).filter(Boolean);
}

export default function CRM1Page() {
    const { user } = useAuth();
    const isAdmin = user?.role === "admin";
    const canManageCommercialFlow = ["admin", "vendedor", "sales_ops", "sucesso_cliente"].includes(user?.role);
    const [clients, setClients] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");
    const [view, setView] = useState(() => localStorage.getItem("crm1:view") || "kanban");
    const [filters, setFilters] = useState({});
    const [selectedClient, setSelectedClient] = useState(null);
    const [showNewClient, setShowNewClient] = useState(false);
    const [showBatchProjects, setShowBatchProjects] = useState(false);
    const [showLossReason, setShowLossReason] = useState(false);
    const [pendingMove, setPendingMove] = useState(null);
    const [pendingProjectMove, setPendingProjectMove] = useState(null);
    const [batchClientId, setBatchClientId] = useState(null);
    const [crmConstants, setCrmConstants] = useState(null);
    const [crmUsers, setCrmUsers] = useState([]);

    useEffect(() => {
        localStorage.setItem("crm1:view", view);
    }, [view]);

    const [newClient, setNewClient] = useState(createEmptyClient());

    const [lossReason, setLossReason] = useState("");
    const [showJustification, setShowJustification] = useState(false);
    const [justificationText, setJustificationText] = useState("");
    const [batchProjects, setBatchProjects] = useState([createEmptyProject()]);
    const [batchProjectError, setBatchProjectError] = useState("");
    const [qualificationModalOpen, setQualificationModalOpen] = useState(false);
    const [qualificationDraft, setQualificationDraft] = useState(null);
    const [qualificationProceedClient, setQualificationProceedClient] = useState(null);
    const [savingQualification, setSavingQualification] = useState(false);

    const loadClients = useCallback(async () => {
        try {
            const params = search ? { search } : {};
            const { data } = await api.get("/crm/clients", { params });
            setClients(data);
        } catch (e) {
            console.error("Failed to load clients", e);
        } finally {
            setLoading(false);
        }
    }, [search]);

    useEffect(() => { loadClients(); }, [loadClients]);

    const loadFormData = useCallback(async () => {
        try {
            const [{ data: constants }, { data: users }] = await Promise.all([
                api.get("/crm/constants"),
                api.get("/crm/users-list"),
            ]);
            setCrmConstants(constants);
            setCrmUsers(users || []);
        } catch (e) {
            console.error("Failed to load CRM metadata", e);
        }
    }, []);

    useEffect(() => { loadFormData(); }, [loadFormData]);

    useEffect(() => {
        setNewClient((current) => (
            current.responsavel_comercial || !user?.id
                ? current
                : { ...current, responsavel_comercial: user.id }
        ));
    }, [user]);

    const categoryGroups = useMemo(() => crmConstants?.categoria_interesse || {}, [crmConstants]);
    const channelGroups = useMemo(() => crmConstants?.canal_origem_grupos || {}, [crmConstants]);
    const channelOptions = useMemo(
        () => flattenUniqueOptions(channelGroups, crmConstants?.canal_origem || []),
        [channelGroups, crmConstants]
    );
    // A4: fonte única de categorias é /crm/constants (categoria_interesse) — sem fallback
    // hardcoded. Enquanto as constants carregam, o grupo fica vazio (nunca com uma lista
    // divergente/desatualizada da real).
    const effectiveCategoryGroups = categoryGroups;
    const effectiveChannelGroups = useMemo(
        () => (Object.keys(channelGroups).length ? channelGroups : (channelOptions.length ? { outros: channelOptions } : {})),
        [channelGroups, channelOptions]
    );
    const segmentOptions = crmConstants?.segmento || [];
    const porteOptions = crmConstants?.porte || [];
    const temperatureOptions = crmConstants?.temperatura_lead || ["quente", "morno", "frio"];
    const cargoOptions = crmConstants?.cargo_decisor || [];
    const ufOptions = crmConstants?.ufs || [];
    const projectPositioningOptions = crmConstants?.project_posicionamento || [];
    const projectServiceOptions = crmConstants?.project_tipo_servico || [];
    const projectRestrictionOptions = crmConstants?.project_restricoes_tecnicas || [];
    const projectCategoryOptions = useMemo(
        () => Object.entries(effectiveCategoryGroups).flatMap(([group, values]) =>
            values.map((value) => ({ value, group, label: formatSlugLabel(value) }))
        ),
        [effectiveCategoryGroups]
    );
    const qualificationMissingFields = useMemo(
        () => (qualificationDraft ? getMissingProjectGateFields(qualificationDraft) : []),
        [qualificationDraft]
    );
    const createProjectDraftForClient = useCallback((client) => createEmptyProject({
        categoria: client?.categoria_interesse?.[0] || "",
        responsavel_comercial: client?.responsavel_comercial || user?.id || "",
    }), [user]);
    // A2: lead de prospecção — criação inicial exige só o nome da empresa. Os demais
    // campos (canal, categoria, temperatura, responsável, segmento, contato) passam a
    // ser exigidos apenas na transição para "qualificado" (validado no backend e
    // sinalizado ao usuário via missingQualificationFields).
    const isNewClientValid = Boolean(newClient.nome_empresa.trim());

    const clientsByStage = STAGES.reduce((acc, stage) => {
        acc[stage.id] = clients.filter(c => c.stage === stage.id);
        return acc;
    }, {});

    // === Filter configuration & filtered data ===
    const filterFields = useMemo(() => ([
        {
            key: "search",
            type: "search",
            placeholder: "Buscar por empresa, CNPJ, contato ou e-mail...",
            searchKeys: [
                (c) => c.nome_empresa,
                (c) => c.cnpj,
                (c) => c.contato_principal?.nome,
                (c) => c.contato_principal?.email,
                (c) => c.contato_principal?.whatsapp,
                (c) => c.segmento,
            ],
        },
        {
            key: "stage",
            type: "multi",
            label: "Fase",
            options: STAGES.map((s) => ({ value: s.id, label: s.label })),
            getter: (c) => c.stage,
        },
        {
            key: "temperatura_lead",
            type: "select",
            label: "Temperatura",
            options: [
                { value: "quente", label: "Quente" },
                { value: "morno", label: "Morno" },
                { value: "frio", label: "Frio" },
            ],
            getter: (c) => c.temperatura_lead,
        },
        {
            key: "categoria_interesse",
            type: "multi",
            label: "Categoria",
            options: Array.from(new Set(clients.flatMap((c) => c.categoria_interesse || []).filter(Boolean)))
                .map((v) => ({ value: v, label: formatSlugLabel(v) })),
            getter: (c) => c.categoria_interesse || [],
        },
        {
            key: "responsavel_comercial",
            type: "select",
            label: "Responsável",
            options: (crmUsers || []).map((u) => ({ value: u.id, label: u.name })),
            getter: (c) => c.responsavel_comercial,
        },
    ]), [clients, crmUsers]);

    const filteredClients = useMemo(() => applyFilters(clients, filters, filterFields), [clients, filters, filterFields]);

    const filteredClientsByStage = useMemo(() => STAGES.reduce((acc, stage) => {
        acc[stage.id] = filteredClients.filter((c) => c.stage === stage.id);
        return acc;
    }, {}), [filteredClients]);

    const userNameById = useMemo(() => Object.fromEntries((crmUsers || []).map((u) => [u.id, u.name])), [crmUsers]);
    const stageLabelById = useMemo(() => Object.fromEntries(STAGES.map((s) => [s.id, s.label])), []);

    const openQualificationModal = useCallback((client, shouldMoveClient = false) => {
        if (!client) return;
        setQualificationDraft(buildQualificationDraft(client));
        setQualificationProceedClient({ ...client, shouldMoveClient });
        setQualificationModalOpen(true);
    }, []);

    const openProjectBatchModal = useCallback((client, shouldMoveClient = false) => {
        if (!client) return;
        const missingGateFields = getMissingProjectGateFields(client);
        if (missingGateFields.length > 0) {
            openQualificationModal(client, shouldMoveClient);
            return;
        }
        setPendingProjectMove(shouldMoveClient ? { clientId: client.id, stage: "projeto_em_discussao", fromStage: client.stage } : null);
        setBatchProjectError("");
        setBatchClientId(client.id);
        setBatchProjects([createProjectDraftForClient(client)]);
        setShowBatchProjects(true);
    }, [createProjectDraftForClient, openQualificationModal]);

    const handleDragEnd = async (result) => {
        if (!result.destination) return;
        const { draggableId, source, destination } = result;
        if (source.droppableId === destination.droppableId) return;

        const newStage = destination.droppableId;
        const client = clients.find(c => c.id === draggableId);
        if (!client) return;

        // Handle cliente_perdido — requires motivo
        if (newStage === "cliente_perdido") {
            setPendingMove({ clientId: draggableId, stage: newStage });
            setLossReason("");
            setShowLossReason(true);
            return;
        }

        // Detect backward (retroactive) move — requires justification
        const currentIdx = STAGE_ORDER.indexOf(client.stage);
        const destIdx = STAGE_ORDER.indexOf(newStage);
        if (destIdx < currentIdx) {
            setPendingMove({ clientId: draggableId, stage: newStage });
            setJustificationText("");
            setShowJustification(true);
            return;
        }

        if (newStage === "projeto_em_discussao") {
            // A passagem Qualificado -> Projeto sempre confirma os produtos de
            // interesse antes de abrir o pre-briefing, mesmo quando os demais
            // dados de qualificacao ja estiverem completos.
            if (client.stage === "qualificado") {
                openQualificationModal(client, true);
                setBatchProjectError("");
                return;
            }
            if (client.stage === "prospeccao" && (client.missing_qualification_fields || []).length > 0) {
                openQualificationModal(client, true);
                setBatchProjectError("");
                return;
            }
            openProjectBatchModal(client, true);
            return;
        }

        try {
            const { data } = await api.put(`/crm/clients/${draggableId}/move`, { stage: newStage });
            toast.success(`Cliente movido para ${data.to_stage}`);

            setBatchProjectError("");
            loadClients();
        } catch (e) {
            const msg = formatApiError(e) || "Erro ao mover cliente";
            toast.error(msg);
        }
    };

    const confirmBackwardMove = async () => {
        if (!pendingMove || !justificationText.trim()) return;
        try {
            const { data } = await api.put(`/crm/clients/${pendingMove.clientId}/move`, {
                stage: pendingMove.stage,
                justificativa: justificationText.trim(),
            });
            toast.success(`Cliente movido para ${data.to_stage}`);
            setShowJustification(false);
            setPendingMove(null);
            setJustificationText("");
            loadClients();
        } catch (e) {
            toast.error(formatApiError(e) || "Erro ao mover cliente");
        }
    };

    const confirmLoss = async () => {
        if (!pendingMove || !lossReason) return;
        try {
            const { data } = await api.put(`/crm/clients/${pendingMove.clientId}/move`, {
                stage: pendingMove.stage, motivo_perda: lossReason,
            });
            toast.success(`Cliente movido para ${data.to_stage}`);
            setShowLossReason(false);
            setPendingMove(null);
            loadClients();
        } catch (e) {
            toast.error(formatApiError(e) || "Erro");
        }
    };

    const handleCreateClient = async () => {
        if (!canManageCommercialFlow) {
            toast.error("Apenas o time Comercial pode criar cards de cliente.");
            return;
        }
        if (!isNewClientValid) return;
        try {
            // Filtrar decisores com nome vazio antes de enviar
            const decisoresValidos = (newClient.decisores || []).filter(d => d.nome.trim());
            const contatosAdicionaisValidos = (newClient.contatos_adicionais || []).filter(hasMeaningfulContactData);
            await api.post("/crm/clients", {
                ...newClient,
                contato_principal: hasMeaningfulContactData(newClient.contato_principal) ? newClient.contato_principal : undefined,
                contatos_adicionais: contatosAdicionaisValidos,
                tem_anvisa: normalizeTemAnvisaValue(newClient.tem_anvisa),
                decisores: decisoresValidos,
            });
            toast.success("Cliente criado!");
            setShowNewClient(false);
            setNewClient(createEmptyClient(user?.id || ""));
            loadClients();
        } catch (e) {
            toast.error(formatApiError(e) || "Erro ao criar cliente");
        }
    };

    const handleQualificationSaveAndProceed = async () => {
        if (!qualificationDraft?.id) return;
        setSavingQualification(true);
        try {
            const payload = {
                contato_principal: qualificationDraft.contato_principal,
                canal_origem: qualificationDraft.canal_origem,
                categoria_interesse: qualificationDraft.categoria_interesse,
                temperatura_lead: qualificationDraft.temperatura_lead,
                responsavel_comercial: qualificationDraft.responsavel_comercial,
                segmento: qualificationDraft.segmento,
                tem_anvisa: normalizeTemAnvisaValue(qualificationDraft.tem_anvisa),
                volume_estimado_mensal: qualificationDraft.volume_estimado_mensal,
                decisores: (qualificationDraft.decisores || []).filter((item) => String(item?.nome || "").trim()),
                fornecedor_atual: qualificationDraft.fornecedor_atual,
            };
            const { data } = await api.put(`/crm/clients/${qualificationDraft.id}`, payload);
            const missing = getMissingProjectGateFields(data);
            setQualificationDraft(buildQualificationDraft(data));
            await loadClients();
            if (missing.length > 0) {
                toast.error(`Ainda faltam campos para liberar o projeto: ${missing.map((field) => QUALIFICATION_FIELD_LABELS[field] || field).join(", ")}`);
                return;
            }
            const proceedClient = qualificationProceedClient;
            setQualificationModalOpen(false);
            setQualificationProceedClient(null);
            setQualificationDraft(null);
            toast.success("Qualificação atualizada!");
            if (proceedClient) {
                openProjectBatchModal(data, Boolean(proceedClient.shouldMoveClient));
            }
        } catch (e) {
            toast.error(formatApiError(e) || "Erro ao salvar qualificação");
        } finally {
            setSavingQualification(false);
        }
    };

    const handleBatchProjectSubmit = async () => {
        if (!canManageCommercialFlow) {
            toast.error("Apenas o time Comercial pode criar cards de projeto.");
            return;
        }
        const valid = batchProjects.filter((project) => (
            project.nome_projeto.trim()
            && project.categoria
            && project.responsavel_comercial
            && project.ideia_conceito.trim()
            && project.posicionamento
            && parseVolumeInput(project.volume_estimado_pedido) > 0
            && project.tipo_servico
            && project.prazo_desejado_amostra
        ));
        if (valid.length === 0 || !batchClientId) {
            setBatchProjectError("Preencha os campos obrigatórios do pré-briefing em pelo menos um projeto.");
            toast.error("Preencha os campos obrigatórios do pré-briefing em pelo menos um projeto.");
            return;
        }
        try {
            setBatchProjectError("");
            const { data } = await api.post("/crm/projects/batch", {
                cliente_id: batchClientId,
                projects: valid.map((project) => ({
                    ...project,
                    faixa_preco_venda: project.faixa_preco_venda ? parsePriceInput(project.faixa_preco_venda) : null,
                    volume_estimado_pedido: project.volume_estimado_pedido ? parseVolumeInput(project.volume_estimado_pedido) : null,
                })),
            });
            // Projects created successfully — now try to advance the client stage separately.
            // If the move fails the projects are already persisted, so we show a partial-success
            // message instead of hiding them behind a generic error.
            toast.success(`${data.count} projeto(s) criado(s)!`);
            setShowBatchProjects(false);
            setPendingProjectMove(null);
            setBatchClientId(null);
            setBatchProjects([createEmptyProject({ responsavel_comercial: user?.id || "" })]);
            if (pendingProjectMove?.clientId === batchClientId) {
                try {
                    const stagesToApply = [];
                    if (pendingProjectMove.fromStage === "prospeccao") {
                        stagesToApply.push("qualificado");
                    }
                    if (pendingProjectMove.fromStage !== pendingProjectMove.stage) {
                        stagesToApply.push(pendingProjectMove.stage);
                    }
                    for (const stage of stagesToApply) {
                        await api.put(`/crm/clients/${batchClientId}/move`, { stage });
                    }
                } catch (moveErr) {
                    toast.error(`Projetos criados, mas não foi possível avançar o cliente: ${formatApiError(moveErr) || "erro desconhecido"}`);
                }
            }
            loadClients();
        } catch (e) {
            const message = formatApiError(e);
            if (batchClientId && /qualifica|ANVISA|decisores|volume|fornecedor/i.test(message || "")) {
                const client = clients.find((item) => item.id === batchClientId) || qualificationProceedClient;
                if (client) {
                    setShowBatchProjects(false);
                    openQualificationModal(client, Boolean(pendingProjectMove));
                }
            }
            setBatchProjectError(message);
            toast.error(message);
        }
    };

    const toggleCategoria = (cat) => {
        const current = newClient.categoria_interesse || [];
        if (current.includes(cat)) {
            setNewClient({ ...newClient, categoria_interesse: current.filter(c => c !== cat) });
        } else {
            setNewClient({ ...newClient, categoria_interesse: [...current, cat] });
        }
    };

    const toggleQualificationCategory = (cat) => {
        setQualificationDraft((current) => {
            const categories = current?.categoria_interesse || [];
            return {
                ...current,
                categoria_interesse: categories.includes(cat)
                    ? categories.filter((item) => item !== cat)
                    : [...categories, cat],
            };
        });
    };

    const updateMainContact = (field, value) => {
        setNewClient((current) => ({
            ...current,
            contato_principal: { ...current.contato_principal, [field]: value },
        }));
    };

    const addAdditionalContact = () => {
        setNewClient((current) => ({
            ...current,
            contatos_adicionais: [...(current.contatos_adicionais || []), { ...EMPTY_ADDITIONAL_CONTACT }],
        }));
    };

    const updateAdditionalContact = (index, field, value) => {
        setNewClient((current) => ({
            ...current,
            contatos_adicionais: current.contatos_adicionais.map((item, itemIndex) => (
                itemIndex === index ? { ...item, [field]: value } : item
            )),
        }));
    };

    const removeAdditionalContact = (index) => {
        setNewClient((current) => ({
            ...current,
            contatos_adicionais: current.contatos_adicionais.filter((_, itemIndex) => itemIndex !== index),
        }));
    };

    const handleDeleteClient = async (client) => {
        if (!isAdmin) {
            toast.error("Apenas administradores podem remover cards de cliente.");
            return;
        }
        if (!client) return;
        if (!window.confirm(`Excluir cliente "${client.nome_empresa}" e todos os projetos/amostras/cards P&D vinculados?`)) return;
        try {
            const { data } = await api.delete(`/crm/clients/${client.id}`);
            toast.success(`Cliente excluído (${data.deleted_projects} projeto(s), ${data.deleted_samples} amostra(s)).`);
            setSelectedClient(null);
            await loadClients();
        } catch (e) {
            toast.error(formatApiError(e) || "Erro ao excluir cliente");
        }
    };

    if (loading) return (
        <div className="p-8 page-enter">
            <div className="animate-pulse space-y-4">
                <div className="h-8 w-64 bg-muted rounded" />
                <div className="flex gap-4">{[1,2,3,4,5,6].map(i => <div key={i} className="h-96 w-72 bg-muted rounded-lg" />)}</div>
            </div>
        </div>
    );

    return (
        <div className="p-6 page-enter" data-testid="crm1-page">
            <CRMSubNav active="clients" />
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h1 className="text-3xl font-heading font-semibold tracking-tight">Pipeline Comercial</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        {filteredClients.length} de {clients.length} clientes
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <ViewSwitcher value={view} onChange={setView} testIdPrefix="crm1" />
                    {canManageCommercialFlow && (
                        <Button onClick={() => { setNewClient(createEmptyClient(user?.id || "")); setShowNewClient(true); }} data-testid="new-client-btn">
                            <Plus className="h-4 w-4 mr-2" /> Novo Cliente
                        </Button>
                    )}
                </div>
            </div>

            <FilterBar
                filters={filters}
                onChange={setFilters}
                fields={filterFields}
                testIdPrefix="crm1-filter"
            />

            {view === "kanban" ? (
            <DragDropContext onDragEnd={handleDragEnd}>
                <div className="kanban-board" data-testid="crm1-kanban">
                    {STAGES.map((stage) => (
                        <Droppable droppableId={stage.id} key={stage.id}>
                            {(provided, snapshot) => (
                                <div
                                    ref={provided.innerRef}
                                    {...provided.droppableProps}
                                    className={`kanban-column rounded-lg ${snapshot.isDraggingOver ? "bg-accent/50" : "bg-muted/30"}`}
                                    data-testid={`crm1-stage-${stage.id}`}
                                >
                                    <div className="p-3 border-b border-border">
                                        <div className="flex items-center gap-2">
                                            <div className={`w-2 h-2 rounded-full ${stage.color}`} />
                                            <h3 className="font-heading font-medium text-sm truncate">{stage.label}</h3>
                                            <span className="text-xs text-muted-foreground mono-num ml-auto">
                                                {(filteredClientsByStage[stage.id] || []).length}
                                            </span>
                                        </div>
                                    </div>
                                    <div className="p-2 space-y-2 min-h-[200px]">
                                        {(filteredClientsByStage[stage.id] || []).map((client, index) => (
                                            <Draggable
                                                draggableId={client.id}
                                                index={index}
                                                key={client.id}
                                                isDragDisabled={client.stage === "cliente_perdido" && !isAdmin}
                                            >
                                                {(provided, snapshot) => (
                                                    <div
                                                        ref={provided.innerRef}
                                                        {...provided.draggableProps}
                                                        className={`bg-card border border-border rounded-md p-3 cursor-pointer transition-transform duration-150 ${
                                                            snapshot.isDragging ? "kanban-card-dragging" : "hover:-translate-y-0.5 hover:shadow-sm"
                                                        }`}
                                                        onClick={() => setSelectedClient(client)}
                                                    >
                                                        <div className="flex items-start justify-between gap-2">
                                                            <div className="flex-1 min-w-0">
                                                                <p className="font-body font-medium text-sm truncate">{client.nome_empresa}</p>
                                                                {client.contato_principal?.nome && (
                                                                    <p className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                                                                        <User className="h-3 w-3" />{client.contato_principal.nome}
                                                                    </p>
                                                                )}
                                                            </div>
                                                            <div {...provided.dragHandleProps} className="shrink-0">
                                                                <GripVertical className="h-4 w-4 text-muted-foreground/50" />
                                                            </div>
                                                        </div>
                                                        <div className="mt-2 flex flex-wrap gap-1">
                                                            {client.temperatura_lead && (
                                                                <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-[0.08em] bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300">
                                                                    {formatSlugLabel(client.temperatura_lead)}
                                                                </span>
                                                            )}
                                                            {client.origem_lead && (
                                                                <span className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300">
                                                                    {client.origem_lead}
                                                                </span>
                                                            )}
                                                            {(client.categoria_interesse || []).slice(0, 2).map(cat => (
                                                                <span key={cat} className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-muted text-muted-foreground">
                                                                    {formatSlugLabel(cat)}
                                                                </span>
                                                            ))}
                                                        </div>
                                                        {client.stage === "prospeccao" && (client.missing_qualification_fields || []).length > 0 && (
                                                            <div className="mt-1.5 flex items-center gap-1 text-[10px] text-amber-600 dark:text-amber-400">
                                                                <AlertTriangle className="h-3 w-3 shrink-0" />
                                                                <span className="truncate">Faltam {client.missing_qualification_fields.length} campo(s) para qualificar</span>
                                                            </div>
                                                        )}
                                                        <div className="mt-1.5 text-[10px] text-muted-foreground mono-num">
                                                            {new Date(client.created_at).toLocaleDateString("pt-BR")}
                                                        </div>
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
                    items={filteredClients}
                    onRowClick={(c) => setSelectedClient(c)}
                    emptyMessage="Nenhum cliente corresponde aos filtros."
                    testIdPrefix="crm1-list"
                    columns={[
                        { key: "nome_empresa", label: "Empresa",
                          render: (c) => <span className="font-medium">{c.nome_empresa}</span> },
                        { key: "cnpj", label: "CNPJ",
                          render: (c) => c.cnpj || "—" },
                        { key: "contato_principal", label: "Contato principal",
                          render: (c) => c.contato_principal?.nome || "—" },
                        { key: "stage", label: "Fase",
                          render: (c) => (
                              <Badge variant="outline" className="text-[10px]">
                                  {stageLabelById[c.stage] || c.stage}
                              </Badge>
                          ) },
                        { key: "temperatura_lead", label: "Temperatura",
                          render: (c) => c.temperatura_lead ? formatSlugLabel(c.temperatura_lead) : "—" },
                        { key: "categoria_interesse", label: "Categorias",
                          render: (c) => (c.categoria_interesse || []).slice(0, 3).map(formatSlugLabel).join(", ") || "—" },
                        { key: "responsavel_comercial", label: "Responsável",
                          render: (c) => userNameById[c.responsavel_comercial] || "—" },
                        { key: "created_at", label: "Criado em",
                          render: (c) => new Date(c.created_at).toLocaleDateString("pt-BR") },
                    ]}
                />
            )}

            {/* Client Detail Sheet */}
            <ClientDetailSheet
                client={selectedClient}
                constants={crmConstants}
                users={crmUsers}
                isAdmin={isAdmin}
                canEdit={canManageCommercialFlow}
                onDelete={handleDeleteClient}
                onCreateProject={(client) => openProjectBatchModal(client, false)}
                onClose={() => { setSelectedClient(null); loadClients(); }}
            />

            {/* New Client Dialog */}
            <Dialog open={showNewClient} onOpenChange={setShowNewClient}>
                <DialogContent className="max-w-lg max-h-[85vh] flex flex-col p-0 overflow-hidden">
                    <DialogHeader className="p-6 pb-2">
                        <DialogTitle className="font-heading">Novo Cliente</DialogTitle>
                    </DialogHeader>
                    <div className="flex-1 min-h-0 overflow-y-auto px-6 pb-2">
                        <div className="space-y-5">
                            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                <div className="space-y-2 md:col-span-2">
                                    <Label>Empresa *</Label>
                                    <Input
                                        value={newClient.nome_empresa}
                                        onChange={(e) => setNewClient({ ...newClient, nome_empresa: e.target.value })}
                                        placeholder="Nome da empresa"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>CNPJ <span className="text-xs text-muted-foreground font-normal">(opcional)</span></Label>
                                    <Input
                                        value={newClient.cnpj}
                                        onChange={(e) => setNewClient({ ...newClient, cnpj: e.target.value })}
                                        placeholder="00.000.000/0000-00"
                                    />
                                </div>
                                <div className="hidden space-y-2">
                                    <Label className="flex items-center gap-1">
                                        Código Cliente Legado (CLI3)
                                        <span className="text-[10px] text-muted-foreground font-normal">— compatibilidade</span>
                                    </Label>
                                    <Input
                                        className="font-mono uppercase tracking-widest"
                                        maxLength={3}
                                        value={newClient.cli3}
                                        placeholder="ABC"
                                        onChange={(e) => setNewClient({ ...newClient, cli3: e.target.value.replace(/[^a-zA-Z]/g, "").toUpperCase().slice(0, 3) })}
                                    />
                                    <p className="text-[10px] text-muted-foreground">Campo legado. O formato atual do SKU usa CAT3-CLI4-SEQ4; se vazio, o sistema mantém só para compatibilidade.</p>
                                </div>
                                <Cli4Field
                                    value={newClient.cli4}
                                    onChange={(v) => setNewClient({ ...newClient, cli4: v })}
                                    nomeEmpresa={newClient.nome_empresa}
                                />
                                <div className="space-y-2">
                                    <Label>Temperatura <span className="text-xs text-muted-foreground font-normal">(para qualificar)</span></Label>
                                    <Select value={newClient.temperatura_lead} onValueChange={(v) => setNewClient({ ...newClient, temperatura_lead: v })}>
                                        <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                        <SelectContent>
                                            {temperatureOptions.map((option) => (
                                                <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            </div>

                            <div className="space-y-3">
                                <div>
                                    <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Contato Principal</h4>
                                    <p className="text-[11px] text-muted-foreground mt-0.5">Pode ser preenchido na etapa de qualificação</p>
                                </div>
                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    <div className="space-y-2">
                                        <Label>Nome <span className="text-xs text-muted-foreground font-normal">(opcional)</span></Label>
                                        <Input placeholder="Nome do contato" value={newClient.contato_principal.nome} onChange={(e) => updateMainContact("nome", e.target.value)} />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Cargo</Label>
                                        <Select value={newClient.contato_principal.cargo || ""} onValueChange={(v) => updateMainContact("cargo", v)}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar cargo" /></SelectTrigger>
                                            <SelectContent>
                                                {cargoOptions.map((c) => <SelectItem key={c} value={c}>{formatSlugLabel(c)}</SelectItem>)}
                                                <SelectItem value="outro">Outro</SelectItem>
                                            </SelectContent>
                                        </Select>
                                        {newClient.contato_principal.cargo === "outro" && (
                                            <Input placeholder="Especifique o cargo" value={newClient.contato_principal.cargo_custom || ""} onChange={(e) => updateMainContact("cargo_custom", e.target.value)} />
                                        )}
                                    </div>
                                    <div className="space-y-2">
                                        <Label>WhatsApp <span className="text-xs text-muted-foreground font-normal">(opcional)</span></Label>
                                        <Input placeholder="+55 com DDD" value={newClient.contato_principal.whatsapp} onChange={(e) => updateMainContact("whatsapp", e.target.value)} />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>E-mail</Label>
                                        <Input placeholder="contato@empresa.com" value={newClient.contato_principal.email} onChange={(e) => updateMainContact("email", e.target.value)} />
                                    </div>
                                </div>
                            </div>

                            <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                    <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Contatos Adicionais</h4>
                                    <Button type="button" variant="outline" size="sm" onClick={addAdditionalContact}>
                                        <Plus className="h-3.5 w-3.5 mr-1" /> Adicionar
                                    </Button>
                                </div>
                                {(newClient.contatos_adicionais || []).map((contact, index) => (
                                    <div key={index} className="rounded-lg border border-border p-3 space-y-3">
                                        <div className="flex items-center justify-between">
                                            <span className="text-xs font-medium text-muted-foreground">Contato {index + 1}</span>
                                            <Button type="button" variant="ghost" size="sm" onClick={() => removeAdditionalContact(index)}>
                                                <Trash2 className="h-3.5 w-3.5 text-red-500" />
                                            </Button>
                                        </div>
                                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                            <Input placeholder="Nome" value={contact.nome} onChange={(e) => updateAdditionalContact(index, "nome", e.target.value)} />
                                            <div className="space-y-2">
                                                <Select value={contact.cargo || ""} onValueChange={(v) => updateAdditionalContact(index, "cargo", v)}>
                                                    <SelectTrigger><SelectValue placeholder="Cargo" /></SelectTrigger>
                                                    <SelectContent>
                                                        {cargoOptions.map((option) => (
                                                            <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                        ))}
                                                        <SelectItem value="outro">Outro</SelectItem>
                                                    </SelectContent>
                                                </Select>
                                                {contact.cargo === "outro" && (
                                                    <Input placeholder="Especifique o cargo" value={contact.cargo_custom || ""} onChange={(e) => updateAdditionalContact(index, "cargo_custom", e.target.value)} />
                                                )}
                                            </div>
                                            <Input placeholder="WhatsApp" value={contact.whatsapp} onChange={(e) => updateAdditionalContact(index, "whatsapp", e.target.value)} />
                                            <Input placeholder="E-mail" value={contact.email} onChange={(e) => updateAdditionalContact(index, "email", e.target.value)} />
                                        </div>
                                    </div>
                                ))}
                            </div>

                            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                <div className="space-y-2">
                                    <Label>Canal de Origem <span className="text-xs text-muted-foreground font-normal">(para qualificar)</span></Label>
                                    <Select value={newClient.canal_origem} onValueChange={(v) => setNewClient({ ...newClient, canal_origem: v })}>
                                        <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                        <SelectContent>
                                            {Object.entries(effectiveChannelGroups).map(([group, values]) => (
                                                <div key={group}>
                                                    <div className="px-2 py-1.5 text-xs font-semibold text-muted-foreground">
                                                        {CANAL_GROUP_LABELS[group] || formatSlugLabel(group)}
                                                    </div>
                                                    {values.map((value) => (
                                                        <SelectItem key={value} value={value}>{formatSlugLabel(value)}</SelectItem>
                                                    ))}
                                                </div>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-2">
                                    <Label>Responsavel Comercial <span className="text-xs text-muted-foreground font-normal">(para qualificar)</span></Label>
                                    <Select value={newClient.responsavel_comercial || ""} onValueChange={(v) => setNewClient({ ...newClient, responsavel_comercial: v })}>
                                        <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                        <SelectContent>
                                            {crmUsers.map((crmUser) => (
                                                <SelectItem key={crmUser.id} value={crmUser.id}>{crmUser.name}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-2">
                                    <Label>Segmento <span className="text-xs text-muted-foreground font-normal">(para qualificar)</span></Label>
                                    <Select value={newClient.segmento || ""} onValueChange={(v) => setNewClient({ ...newClient, segmento: v })}>
                                        <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                        <SelectContent>
                                            {segmentOptions.map((option) => (
                                                <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-2">
                                    <Label>Porte</Label>
                                    <Select value={newClient.porte || ""} onValueChange={(v) => setNewClient({ ...newClient, porte: v })}>
                                        <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                        <SelectContent>
                                            {porteOptions.map((option) => (
                                                <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-2">
                                    <Label>UF</Label>
                                    <Select value={newClient.regiao || ""} onValueChange={(v) => setNewClient({ ...newClient, regiao: v })}>
                                        <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                        <SelectContent>
                                            {ufOptions.map((option) => (
                                                <SelectItem key={option} value={option}>{option}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-2">
                                    <Label>Site / Instagram</Label>
                                    <Input
                                        placeholder="https://site.com ou @instagram"
                                        value={newClient.site}
                                        onChange={(e) => setNewClient({ ...newClient, site: e.target.value })}
                                    />
                                </div>
                            </div>

                            <div className="space-y-2">
                                <Label>Categorias de Interesse <span className="text-xs text-muted-foreground font-normal">(para qualificar)</span></Label>
                                <div className="space-y-3 rounded-lg border border-border p-3">
                                    {Object.entries(effectiveCategoryGroups).map(([group, values]) => (
                                        <div key={group} className="space-y-2">
                                            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                                                {formatSlugLabel(group)}
                                            </p>
                                            <div className="flex flex-wrap gap-2">
                                                {values.map((value) => (
                                                    <button
                                                        key={value}
                                                        type="button"
                                                        onClick={() => toggleCategoria(value)}
                                                        className={`px-3 py-1 rounded-md text-xs font-medium border transition-colors ${
                                                            (newClient.categoria_interesse || []).includes(value)
                                                                ? "bg-primary text-primary-foreground border-primary"
                                                                : "bg-muted text-muted-foreground border-border hover:bg-accent"
                                                        }`}
                                                    >
                                                        {formatSlugLabel(value)}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                                {(newClient.categoria_interesse || []).length === 0 && (
                                    <p className="text-xs text-destructive">Selecione ao menos uma categoria de interesse.</p>
                                )}
                            </div>

                            <div className="space-y-2">
                                <Label>Origem do Lead (detalhe)</Label>
                                <Input
                                    value={newClient.origem_lead}
                                    onChange={(e) => setNewClient({ ...newClient, origem_lead: e.target.value })}
                                    placeholder="Ex: Indicacao do cliente Habibi Perfumes"
                                />
                            </div>

                            <div className="space-y-2">
                                <Label>Instagram</Label>
                                <Input
                                    value={newClient.instagram}
                                    onChange={(e) => setNewClient({ ...newClient, instagram: e.target.value })}
                                    placeholder="@cliente"
                                />
                            </div>

                            <div className="space-y-2">
                                <Label>Observacoes</Label>
                                <Textarea
                                    value={newClient.observacoes}
                                    onChange={(e) => setNewClient({ ...newClient, observacoes: e.target.value })}
                                    placeholder="Contexto geral sobre o cliente"
                                    rows={4}
                                />
                            </div>

                            {/* ── Qualificação ──────────────────────────── */}
                            <div className="rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 p-4 space-y-4">
                                <div className="flex items-start gap-2">
                                    <div className="mt-0.5 h-4 w-4 shrink-0 text-amber-600">
                                        <svg viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" /></svg>
                                    </div>
                                    <div className="hidden">
                                        <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">Qualificação (preencha para avançar diretamente para Projeto em Discussão)</p>
                                        <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-0.5">Sem estes campos, o sistema bloqueará o avanço até que sejam preenchidos.</p>
                                    </div>
                                </div>

                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    <div className="space-y-1.5">
                                        <Label className="text-xs">Tem ANVISA? *</Label>
                                        <Select value={normalizeTemAnvisaValue(newClient.tem_anvisa)} onValueChange={(v) => setNewClient({ ...newClient, tem_anvisa: normalizeTemAnvisaValue(v) })}>
                                            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {ANVISA_OPTIONS.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label className="text-xs">Volume Estimado Mensal *</Label>
                                        <Select value={newClient.volume_estimado_mensal} onValueChange={(v) => setNewClient({ ...newClient, volume_estimado_mensal: v })}>
                                            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {VOLUME_OPTIONS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </div>

                                <div className="space-y-1.5">
                                    <div className="flex items-center justify-between">
                                        <Label className="text-xs">Decisores *</Label>
                                        <button
                                            type="button"
                                            className="text-[10px] text-primary hover:underline"
                                            onClick={() => setNewClient(c => ({ ...c, decisores: [...(c.decisores || []), { nome: "", cargo: "", contato: "" }] }))}
                                        >+ Adicionar</button>
                                    </div>
                                    {(newClient.decisores || []).map((dec, idx) => (
                                        <div key={idx} className="flex gap-2 items-center">
                                            <input
                                                className="flex-1 h-7 rounded border border-input bg-background px-2 text-xs"
                                                placeholder="Nome do decisor *"
                                                value={dec.nome}
                                                onChange={e => {
                                                    const d = [...newClient.decisores];
                                                    d[idx] = { ...d[idx], nome: e.target.value };
                                                    setNewClient(c => ({ ...c, decisores: d }));
                                                }}
                                            />
                                            <select
                                                className="h-7 rounded border border-input bg-background px-2 text-xs"
                                                value={dec.cargo}
                                                onChange={e => {
                                                    const d = [...newClient.decisores];
                                                    d[idx] = { ...d[idx], cargo: e.target.value };
                                                    setNewClient(c => ({ ...c, decisores: d }));
                                                }}
                                            >
                                                <option value="">Cargo</option>
                                                {["ceo", "comprador", "desenvolvimento", "diretor_comercial", "gerente_produto", "outro"].map(c => (
                                                    <option key={c} value={c}>{formatSlugLabel(c)}</option>
                                                ))}
                                            </select>
                                            <input
                                                className="w-28 h-7 rounded border border-input bg-background px-2 text-xs"
                                                placeholder="WhatsApp"
                                                value={dec.contato}
                                                onChange={e => {
                                                    const d = [...newClient.decisores];
                                                    d[idx] = { ...d[idx], contato: e.target.value };
                                                    setNewClient(c => ({ ...c, decisores: d }));
                                                }}
                                            />
                                            {(newClient.decisores || []).length > 1 && (
                                                <button type="button" className="text-muted-foreground hover:text-red-500" onClick={() => {
                                                    setNewClient(c => ({ ...c, decisores: c.decisores.filter((_, i) => i !== idx) }));
                                                }}>×</button>
                                            )}
                                        </div>
                                    ))}
                                    <p className="text-[10px] text-amber-700 dark:text-amber-400">Preencha ao menos o nome de um decisor.</p>
                                </div>

                                <div className="space-y-1.5">
                                    <div className="flex items-center gap-2">
                                        <input
                                            type="checkbox"
                                            id="new-client-tem-fornecedor"
                                            checked={newClient.fornecedor_atual?.tem || false}
                                            onChange={e => setNewClient(c => ({ ...c, fornecedor_atual: { ...c.fornecedor_atual, tem: e.target.checked } }))}
                                            className="h-3.5 w-3.5 accent-primary"
                                        />
                                        <Label htmlFor="new-client-tem-fornecedor" className="text-xs cursor-pointer">Possui fornecedor atual?</Label>
                                    </div>
                                    {newClient.fornecedor_atual?.tem && (
                                        <input
                                            className="w-full h-7 rounded border border-input bg-background px-2 text-xs"
                                            placeholder="Motivo da troca de fornecedor"
                                            value={newClient.fornecedor_atual?.motivo_troca || ""}
                                            onChange={e => setNewClient(c => ({ ...c, fornecedor_atual: { ...c.fornecedor_atual, motivo_troca: e.target.value } }))}
                                        />
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                    <DialogFooter className="p-6 pt-3 border-t">
                        <Button variant="outline" onClick={() => setShowNewClient(false)}>Cancelar</Button>
                        <Button onClick={handleCreateClient} disabled={!isNewClientValid}>Criar Cliente</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Loss Reason Dialog */}
            <Dialog open={showLossReason} onOpenChange={(v) => { if (!v) { setShowLossReason(false); setPendingMove(null); } }}>
                <DialogContent className="max-w-md">
                    <DialogHeader>
                        <DialogTitle className="font-heading flex items-center gap-2">
                            <AlertTriangle className="h-5 w-5 text-red-500" /> Cliente Perdido
                        </DialogTitle>
                    </DialogHeader>
                    <div className="space-y-3">
                        <Label>Motivo da perda *</Label>
                        <Select value={lossReason} onValueChange={setLossReason}>
                            <SelectTrigger>
                                <SelectValue placeholder="Selecione o motivo" />
                            </SelectTrigger>
                            <SelectContent>
                                {LOSS_REASON_OPTIONS.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => { setShowLossReason(false); setPendingMove(null); }}>Cancelar</Button>
                        <Button variant="destructive" onClick={confirmLoss} disabled={!lossReason}>Confirmar Perda</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Backward Move Justification Dialog */}
            <Dialog open={showJustification} onOpenChange={(v) => { if (!v) { setShowJustification(false); setPendingMove(null); } }}>
                <DialogContent className="max-w-md">
                    <DialogHeader>
                        <DialogTitle className="font-heading flex items-center gap-2">
                            <AlertTriangle className="h-5 w-5 text-amber-500" /> Movimentação Retroativa
                        </DialogTitle>
                    </DialogHeader>
                    <div className="space-y-3">
                        <p className="text-sm text-muted-foreground">
                            Você está movendo o cliente para um estágio anterior. Informe a justificativa para esta movimentação.
                        </p>
                        <Label>Justificativa *</Label>
                        <Textarea
                            rows={3}
                            placeholder="Descreva o motivo da movimentação retroativa..."
                            value={justificationText}
                            onChange={(e) => setJustificationText(e.target.value)}
                        />
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => { setShowJustification(false); setPendingMove(null); }}>Cancelar</Button>
                        <Button onClick={confirmBackwardMove} disabled={!justificationText.trim()}>Confirmar Movimentação</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={qualificationModalOpen} onOpenChange={(open) => {
                setQualificationModalOpen(open);
                if (!open) {
                    setQualificationProceedClient(null);
                    setQualificationDraft(null);
                }
            }}>
                <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col p-0 overflow-hidden">
                    <DialogHeader className="p-6 pb-3 border-b">
                        <DialogTitle className="font-heading flex items-center gap-2">
                            <AlertTriangle className="h-5 w-5 text-amber-500" /> Qualificação obrigatória antes do projeto
                        </DialogTitle>
                        <p className="text-sm text-muted-foreground">
                            Preencha os campos abaixo para liberar a criação do projeto para {qualificationDraft?.nome_empresa || "este cliente"}.
                        </p>
                    </DialogHeader>
                    <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-5">
                        {qualificationMissingFields.length > 0 && (
                            <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 p-3">
                                <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">Campos pendentes</p>
                                <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                                    {qualificationMissingFields.map((field) => QUALIFICATION_FIELD_LABELS[field] || field).join(", ")}
                                </p>
                            </div>
                        )}

                        {qualificationDraft && (
                            <>
                                <div className="space-y-2">
                                    <Label>Categorias de Interesse</Label>
                                    <div className="flex flex-wrap gap-2">
                                        {projectCategoryOptions.map((option) => {
                                            const active = (qualificationDraft.categoria_interesse || []).includes(option.value);
                                            return (
                                                <button
                                                    key={`${option.group}-${option.value}`}
                                                    type="button"
                                                    className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${active ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:bg-accent hover:text-accent-foreground"}`}
                                                    onClick={() => toggleQualificationCategory(option.value)}
                                                >
                                                    {option.label}
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>

                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    <div className="space-y-2">
                                        <Label>Tem ANVISA?</Label>
                                        <Select value={qualificationDraft.tem_anvisa || ""} onValueChange={(value) => setQualificationDraft((current) => ({ ...current, tem_anvisa: normalizeTemAnvisaValue(value) }))}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {ANVISA_OPTIONS.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Volume Estimado Mensal</Label>
                                        <Select value={qualificationDraft.volume_estimado_mensal || ""} onValueChange={(value) => setQualificationDraft((current) => ({ ...current, volume_estimado_mensal: value }))}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {VOLUME_OPTIONS.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </div>

                                <Separator />

                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    <div className="space-y-2">
                                        <Label>Contato - Nome</Label>
                                        <Input
                                            value={qualificationDraft.contato_principal?.nome || ""}
                                            onChange={(e) => setQualificationDraft((current) => ({
                                                ...current,
                                                contato_principal: { ...current.contato_principal, nome: e.target.value },
                                            }))}
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Contato - WhatsApp</Label>
                                        <Input
                                            value={qualificationDraft.contato_principal?.whatsapp || ""}
                                            onChange={(e) => setQualificationDraft((current) => ({
                                                ...current,
                                                contato_principal: { ...current.contato_principal, whatsapp: e.target.value },
                                            }))}
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Canal de Origem</Label>
                                        <Select value={qualificationDraft.canal_origem || ""} onValueChange={(value) => setQualificationDraft((current) => ({ ...current, canal_origem: value }))}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {channelOptions.map((value) => (
                                                    <SelectItem key={value} value={value}>{formatSlugLabel(value)}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Temperatura</Label>
                                        <Select value={qualificationDraft.temperatura_lead || ""} onValueChange={(value) => setQualificationDraft((current) => ({ ...current, temperatura_lead: value }))}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {temperatureOptions.map((option) => (
                                                    <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Responsável Comercial</Label>
                                        <Select value={qualificationDraft.responsavel_comercial || ""} onValueChange={(value) => setQualificationDraft((current) => ({ ...current, responsavel_comercial: value }))}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {crmUsers.map((crmUser) => (
                                                    <SelectItem key={crmUser.id} value={crmUser.id}>{crmUser.name}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Segmento</Label>
                                        <Select value={qualificationDraft.segmento || ""} onValueChange={(value) => setQualificationDraft((current) => ({ ...current, segmento: value }))}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {segmentOptions.map((option) => (
                                                    <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <Label>Decisores</Label>
                                        <Button
                                            type="button"
                                            variant="outline"
                                            size="sm"
                                            onClick={() => setQualificationDraft((current) => ({
                                                ...current,
                                                decisores: [...(current.decisores || []), { nome: "", cargo: "", contato: "" }],
                                            }))}
                                        >
                                            <Plus className="h-3.5 w-3.5 mr-1" /> Adicionar
                                        </Button>
                                    </div>
                                    <div className="space-y-2">
                                        {(qualificationDraft.decisores || []).map((decisor, idx) => (
                                            <div key={idx} className="grid grid-cols-1 gap-2 rounded-md border border-border p-3 md:grid-cols-[1.2fr_1fr_1fr_auto]">
                                                <Input
                                                    placeholder="Nome do decisor"
                                                    value={decisor.nome || ""}
                                                    onChange={(e) => setQualificationDraft((current) => {
                                                        const next = [...(current.decisores || [])];
                                                        next[idx] = { ...next[idx], nome: e.target.value };
                                                        return { ...current, decisores: next };
                                                    })}
                                                />
                                                <Select
                                                    value={decisor.cargo || ""}
                                                    onValueChange={(value) => setQualificationDraft((current) => {
                                                        const next = [...(current.decisores || [])];
                                                        next[idx] = { ...next[idx], cargo: value };
                                                        return { ...current, decisores: next };
                                                    })}
                                                >
                                                    <SelectTrigger><SelectValue placeholder="Cargo" /></SelectTrigger>
                                                    <SelectContent>
                                                        {cargoOptions.map((cargo) => (
                                                            <SelectItem key={cargo} value={cargo}>{formatSlugLabel(cargo)}</SelectItem>
                                                        ))}
                                                    </SelectContent>
                                                </Select>
                                                <Input
                                                    placeholder="Contato"
                                                    value={decisor.contato || ""}
                                                    onChange={(e) => setQualificationDraft((current) => {
                                                        const next = [...(current.decisores || [])];
                                                        next[idx] = { ...next[idx], contato: e.target.value };
                                                        return { ...current, decisores: next };
                                                    })}
                                                />
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() => setQualificationDraft((current) => ({
                                                        ...current,
                                                        decisores: (current.decisores || []).filter((_, decisorIndex) => decisorIndex !== idx),
                                                    }))}
                                                >
                                                    Remover
                                                </Button>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <div className="flex items-center gap-2">
                                        <Switch
                                            checked={Boolean(qualificationDraft.fornecedor_atual?.tem)}
                                            onCheckedChange={(checked) => setQualificationDraft((current) => ({
                                                ...current,
                                                fornecedor_atual: {
                                                    ...current.fornecedor_atual,
                                                    tem: checked,
                                                    motivo_troca: checked ? current.fornecedor_atual?.motivo_troca || "" : "",
                                                },
                                            }))}
                                        />
                                        <Label>Possui fornecedor atual?</Label>
                                    </div>
                                    {qualificationDraft.fornecedor_atual?.tem && (
                                        <Input
                                            placeholder="Motivo da troca de fornecedor"
                                            value={qualificationDraft.fornecedor_atual?.motivo_troca || ""}
                                            onChange={(e) => setQualificationDraft((current) => ({
                                                ...current,
                                                fornecedor_atual: { ...current.fornecedor_atual, motivo_troca: e.target.value },
                                            }))}
                                        />
                                    )}
                                </div>
                            </>
                        )}
                    </div>
                    <DialogFooter className="p-6 pt-3 border-t">
                        <Button variant="outline" onClick={() => {
                            setQualificationModalOpen(false);
                            setQualificationProceedClient(null);
                            setQualificationDraft(null);
                        }}>
                            Cancelar
                        </Button>
                        <Button onClick={handleQualificationSaveAndProceed} disabled={!qualificationDraft || savingQualification}>
                            {savingQualification ? "Salvando..." : "Salvar e prosseguir"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Batch Project Creation Modal */}
            <Dialog open={showBatchProjects} onOpenChange={(open) => {
                setShowBatchProjects(open);
                if (!open) {
                    setBatchProjectError("");
                    setPendingProjectMove(null);
                    setBatchClientId(null);
                    setBatchProjects([createEmptyProject({ responsavel_comercial: user?.id || "" })]);
                }
            }}>
                <DialogContent className="max-w-5xl max-h-[90vh] flex flex-col p-0 overflow-hidden">
                    <DialogHeader className="p-6 pb-2">
                        <DialogTitle className="font-heading">Criar Projetos em Lote</DialogTitle>
                        <p className="text-sm text-muted-foreground">Adicione os projetos que serão desenvolvidos para este cliente.</p>
                    </DialogHeader>
                    <div className="flex-1 min-h-0 overflow-y-auto px-6 pb-2">
                        <div className="space-y-3">
                            {batchProjects.map((proj, idx) => (
                                <div key={idx} className="border border-border rounded-lg p-4 space-y-3 bg-card">
                                    <div className="flex items-center justify-between">
                                        <span className="text-xs font-semibold text-muted-foreground">Projeto {idx + 1}</span>
                                        {batchProjects.length > 1 && (
                                            <Button variant="ghost" size="sm" onClick={() => setBatchProjects(batchProjects.filter((_, i) => i !== idx))}>
                                                <Trash2 className="h-3.5 w-3.5 text-red-500" />
                                            </Button>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Nome do projeto *</Label>
                                            <Input placeholder="Ex: Habibi / Body Splash 300ml" value={proj.nome_projeto}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], nome_projeto: e.target.value }; setBatchProjects(p); }} />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Categoria do produto *</Label>
                                            <Select value={proj.categoria} onValueChange={(v) => { const p = [...batchProjects]; p[idx] = { ...p[idx], categoria: v }; setBatchProjects(p); }}>
                                                <SelectTrigger><SelectValue placeholder="Categoria" /></SelectTrigger>
                                                <SelectContent>
                                                    {projectCategoryOptions.map((option) => (
                                                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Responsável comercial *</Label>
                                            <Select value={proj.responsavel_comercial} onValueChange={(v) => { const p = [...batchProjects]; p[idx] = { ...p[idx], responsavel_comercial: v }; setBatchProjects(p); }}>
                                                <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                                <SelectContent>
                                                    {crmUsers.map((crmUser) => (
                                                        <SelectItem key={crmUser.id} value={crmUser.id}>{crmUser.name}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Ideia / conceito do produto *</Label>
                                            <Textarea placeholder="Descreva o que o cliente quer desenvolver." value={proj.ideia_conceito} rows={3}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], ideia_conceito: e.target.value, briefing_resumido: e.target.value }; setBatchProjects(p); }} />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Referência de mercado</Label>
                                            <Input placeholder="Concorrente ou inspiração" value={proj.referencia_mercado}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], referencia_mercado: e.target.value }; setBatchProjects(p); }} />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Público-alvo</Label>
                                            <Input placeholder="A quem o produto se destina" value={proj.publico_alvo}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], publico_alvo: e.target.value }; setBatchProjects(p); }} />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Posicionamento *</Label>
                                            <Select value={proj.posicionamento} onValueChange={(v) => { const p = [...batchProjects]; p[idx] = { ...p[idx], posicionamento: v }; setBatchProjects(p); }}>
                                                <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                                <SelectContent>
                                                    {projectPositioningOptions.map((option) => (
                                                        <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Tipo de serviço *</Label>
                                            <Select value={proj.tipo_servico} onValueChange={(v) => { const p = [...batchProjects]; p[idx] = { ...p[idx], tipo_servico: v }; setBatchProjects(p); }}>
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
                                            <Input type="text" inputMode="decimal" placeholder={DEFAULT_PRICE_DISPLAY} value={proj.faixa_preco_venda}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], faixa_preco_venda: e.target.value }; setBatchProjects(p); }}
                                                onFocus={() => {
                                                    if (proj.faixa_preco_venda) return;
                                                    const p = [...batchProjects];
                                                    p[idx] = { ...p[idx], faixa_preco_venda: seedPriceDisplay(proj.faixa_preco_venda) };
                                                    setBatchProjects(p);
                                                }}
                                                onBlur={() => { const fmt = fmtPriceDisplay(proj.faixa_preco_venda); if (fmt !== "" && fmt !== String(proj.faixa_preco_venda)) { const p = [...batchProjects]; p[idx] = { ...p[idx], faixa_preco_venda: fmt }; setBatchProjects(p); } }} />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Volume estimado por pedido *</Label>
                                            <Input type="text" inputMode="numeric" placeholder={DEFAULT_VOLUME_DISPLAY} value={proj.volume_estimado_pedido}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], volume_estimado_pedido: e.target.value }; setBatchProjects(p); }}
                                                onFocus={() => {
                                                    if (proj.volume_estimado_pedido) return;
                                                    const p = [...batchProjects];
                                                    p[idx] = { ...p[idx], volume_estimado_pedido: seedVolumeDisplay(proj.volume_estimado_pedido) };
                                                    setBatchProjects(p);
                                                }}
                                                onBlur={() => { const fmt = fmtVolumeDisplay(proj.volume_estimado_pedido); if (fmt !== "" && fmt !== String(proj.volume_estimado_pedido)) { const p = [...batchProjects]; p[idx] = { ...p[idx], volume_estimado_pedido: fmt }; setBatchProjects(p); } }} />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Prazo desejado para amostra *</Label>
                                            <Input type="date" value={proj.prazo_desejado_amostra}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], prazo_desejado_amostra: e.target.value }; setBatchProjects(p); }} />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Sensorial desejado</Label>
                                            <Input placeholder="Textura, cor, fragrância" value={proj.sensorial_desejado}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], sensorial_desejado: e.target.value }; setBatchProjects(p); }} />
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Claims desejados</Label>
                                            <Textarea value={proj.claims_desejados} rows={2}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], claims_desejados: e.target.value }; setBatchProjects(p); }} />
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Restrições técnicas</Label>
                                            <div className="flex flex-wrap gap-2">
                                                {projectRestrictionOptions.map((option) => {
                                                    const active = (proj.restricoes_tecnicas || []).includes(option);
                                                    return (
                                                        <button
                                                            key={option}
                                                            type="button"
                                                            className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${active ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:bg-accent"}`}
                                                            onClick={() => {
                                                                const current = proj.restricoes_tecnicas || [];
                                                                const next = current.includes(option)
                                                                    ? current.filter((item) => item !== option)
                                                                    : [...current, option];
                                                                const p = [...batchProjects];
                                                                p[idx] = { ...p[idx], restricoes_tecnicas: next };
                                                                setBatchProjects(p);
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
                                            <Textarea value={proj.observacoes_livres} rows={2}
                                                onChange={(e) => { const p = [...batchProjects]; p[idx] = { ...p[idx], observacoes_livres: e.target.value }; setBatchProjects(p); }} />
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <Button variant="outline" className="w-full mt-3" onClick={() => setBatchProjects([...batchProjects, createProjectDraftForClient(clients.find((client) => client.id === batchClientId))])}>
                            <Plus className="h-4 w-4 mr-2" /> Adicionar Projeto
                        </Button>
                        {batchProjectError && (
                            <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                                {batchProjectError}
                            </div>
                        )}
                    </div>
                    <DialogFooter className="p-6 pt-3 border-t">
                        <Button variant="outline" onClick={() => { setShowBatchProjects(false); setBatchProjectError(""); setPendingProjectMove(null); setBatchClientId(null); setBatchProjects([createEmptyProject({ responsavel_comercial: user?.id || "" })]); }}>Cancelar</Button>
                        <Button onClick={handleBatchProjectSubmit}>
                            Criar {batchProjects.filter((project) => project.nome_projeto.trim()).length} Projeto(s)
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}


// ======= Client Detail Sheet =======
function ClientDetailSheet({ client, constants, isAdmin = false, canEdit = false, onClose, onCreateProject, onDelete }) {
    const [data, setData] = useState(null);
    const [fullData, setFullData] = useState(null);
    const [editing, setEditing] = useState({});
    const [saving, setSaving] = useState(false);
    const [tab, setTab] = useState("info");
    const detailChannelOptions = useMemo(
        () => flattenUniqueOptions(constants?.canal_origem_grupos || {}, constants?.canal_origem || []),
        [constants]
    );
    const detailLeadOriginOptions = constants?.origem_lead || [];
    const detailCargoOptions = constants?.cargo_decisor || [];

    useEffect(() => {
        if (client) {
            setData({ ...client });
            setEditing({});
            setTab("info");
            setFullData(null);
            api.get(`/crm/clients/${client.id}/full`).then(({ data: fd }) => setFullData(fd)).catch(() => {});
        } else {
            setData(null);
            setFullData(null);
        }
    }, [client]);

    const stageIndex = STAGE_ORDER.indexOf(data?.stage || "prospeccao");

    const handleSave = async () => {
        if (!data) return;
        if (!canEdit) {
            toast.error("Apenas o time Comercial pode editar cards de cliente.");
            setEditing({});
            return;
        }
        setSaving(true);
        try {
            const updates = {};
            for (const [k, v] of Object.entries(editing)) {
                if (v !== undefined) updates[k] = v;
            }
            if (Object.keys(updates).length > 0) {
                if ("tem_anvisa" in updates) {
                    updates.tem_anvisa = normalizeTemAnvisaValue(updates.tem_anvisa);
                }
                const resp = await api.put(`/crm/clients/${data.id}`, updates);
                setData(resp.data);
                setFullData((prev) => (prev ? { ...prev, client: resp.data } : prev));
                toast.success("Cliente atualizado!");
            }
            setEditing({});
        } catch (e) {
            toast.error(formatApiError(e) || "Erro ao salvar");
        } finally {
            setSaving(false);
        }
    };

    const val = (field) => editing[field] !== undefined ? editing[field] : (data?.[field] ?? "");
    const setVal = (field, value) => setEditing({ ...editing, [field]: value });
    const decisores = Array.isArray(val("decisores")) ? val("decisores") : (Array.isArray(data?.decisores) ? data.decisores : []);
    const fornecedorAtual = (() => {
        const current = val("fornecedor_atual");
        if (current && typeof current === "object" && !Array.isArray(current)) return current;
        return data?.fornecedor_atual || { tem: false, motivo_troca: "" };
    })();
    const temAnvisaValue = normalizeTemAnvisaValue(val("tem_anvisa"));

    if (!data) return null;

    return (
        <Sheet open={!!client} onOpenChange={(v) => { if (!v) onClose(); }}>
            <SheetContent className="w-[500px] sm:w-[550px] p-0 flex flex-col" side="right">
                <SheetHeader className="p-6 pb-3">
                    <SheetTitle className="font-heading text-xl">{data.nome_empresa}</SheetTitle>
                    <div className="flex items-center gap-2 mt-1">
                        <Badge variant="outline" className="text-xs">
                            {STAGES.find(s => s.id === data.stage)?.label || data.stage}
                        </Badge>
                        {data.cnpj && <span className="text-xs text-muted-foreground mono-num">{data.cnpj}</span>}
                    </div>
                    {canEdit && stageIndex >= 2 && (
                        <div className="pt-3">
                            <Button variant="outline" size="sm" onClick={() => onCreateProject?.(data)}>
                                <Plus className="h-4 w-4 mr-2" /> Novo Projeto para este Cliente
                            </Button>
                        </div>
                    )}
                </SheetHeader>
                <Separator />
                <Tabs value={tab} onValueChange={setTab} className="flex-1 flex flex-col min-h-0">
                    <TabsList className="mx-6 mt-3 flex-wrap h-auto">
                        <TabsTrigger value="info">Dados</TabsTrigger>
                        <TabsTrigger value="projetos">Projetos {fullData ? `(${fullData.projects?.length || 0})` : ""}</TabsTrigger>
                        <TabsTrigger value="pedidos">Pedidos {fullData ? `(${fullData.orders?.length || 0})` : ""}</TabsTrigger>
                        <TabsTrigger value="contatos">Contatos</TabsTrigger>
                        <TabsTrigger value="timeline">Histórico</TabsTrigger>
                    </TabsList>

                    <TabsContent value="info" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3">
                        <div className="space-y-5">
                            {data.stage === "prospeccao" && (data.missing_qualification_fields || []).length > 0 && (
                                <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 p-3">
                                    <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 flex items-center gap-1.5">
                                        <AlertTriangle className="h-3.5 w-3.5" /> Faltam preencher para qualificar este lead:
                                    </p>
                                    <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                                        {data.missing_qualification_fields.map((f) => QUALIFICATION_FIELD_LABELS[f] || f).join(", ")}
                                    </p>
                                </div>
                            )}
                            {/* Prospecção — always visible */}
                            <section>
                                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Prospecção</h4>
                                <div className="space-y-3">
                                    <div><Label className="text-xs">Empresa</Label><Input value={val("nome_empresa")} onChange={(e) => setVal("nome_empresa", e.target.value)} /></div>
                                    <div><Label className="text-xs">CNPJ</Label><Input value={val("cnpj")} onChange={(e) => setVal("cnpj", e.target.value)} /></div>
                                    <div className="hidden">
                                        <Label className="text-xs flex items-center gap-1">
                                            Código Cliente Legado (CLI3)
                                            <span className="text-[10px] text-muted-foreground font-normal">— compatibilidade</span>
                                        </Label>
                                        <div className="flex items-center gap-2 mt-1">
                                            <Input
                                                className="h-8 w-24 font-mono uppercase text-center tracking-widest text-sm"
                                                maxLength={3}
                                                value={val("cli3") || ""}
                                                placeholder="ABC"
                                                onChange={(e) => setVal("cli3", e.target.value.replace(/[^a-zA-Z]/g, "").toUpperCase().slice(0, 3))}
                                            />
                                            {(val("cli3") || data?.cli3) && (
                                                <span className="text-[11px] text-muted-foreground font-mono bg-muted px-2 py-0.5 rounded">
                                                    legado: XXX-{(val("cli3") || data?.cli3 || "???").toUpperCase()}-0001
                                                </span>
                                            )}
                                        </div>
                                        {(val("cli3") || "").length > 0 && (val("cli3") || "").length < 3 && (
                                            <p className="text-[10px] text-amber-600 mt-0.5">Precisa de exatamente 3 letras</p>
                                        )}
                                    </div>
                                    <Cli4Field
                                        value={val("cli4") ?? data?.cli4}
                                        onChange={(v) => setVal("cli4", v)}
                                        nomeEmpresa={val("nome_empresa") ?? data?.nome_empresa}
                                        frozen={Boolean(data?.cli4_congelado)}
                                    />
                                    <div><Label className="text-xs">Contato — Nome</Label><Input value={val("contato_principal")?.nome || data.contato_principal?.nome || ""} onChange={(e) => setVal("contato_principal", { ...(data.contato_principal || {}), ...(editing.contato_principal || {}), nome: e.target.value })} /></div>
                                    <div>
                                        <Label className="text-xs">Contato — Cargo</Label>
                                        <Select value={(val("contato_principal") ?? data.contato_principal)?.cargo || ""} onValueChange={(v) => setVal("contato_principal", { ...(data.contato_principal || {}), ...(editing.contato_principal || {}), cargo: v })}>
                                            <SelectTrigger><SelectValue placeholder="Cargo" /></SelectTrigger>
                                            <SelectContent>
                                                {(constants?.cargo_decisor || []).map((c) => <SelectItem key={c} value={c}>{formatSlugLabel(c)}</SelectItem>)}
                                                <SelectItem value="outro">Outro</SelectItem>
                                            </SelectContent>
                                        </Select>
                                        {((val("contato_principal") ?? data.contato_principal)?.cargo === "outro") && (
                                            <Input className="mt-2" placeholder="Especifique o cargo" value={(val("contato_principal") ?? data.contato_principal)?.cargo_custom || ""} onChange={(e) => setVal("contato_principal", { ...(data.contato_principal || {}), ...(editing.contato_principal || {}), cargo_custom: e.target.value })} />
                                        )}
                                    </div>
                                    <div><Label className="text-xs">Contato — WhatsApp</Label><Input value={val("contato_principal")?.whatsapp || data.contato_principal?.whatsapp || ""} onChange={(e) => setVal("contato_principal", { ...(data.contato_principal || {}), ...(editing.contato_principal || {}), whatsapp: e.target.value })} /></div>
                                    <div><Label className="text-xs">Contato — Email</Label><Input value={val("contato_principal")?.email || data.contato_principal?.email || ""} onChange={(e) => setVal("contato_principal", { ...(data.contato_principal || {}), ...(editing.contato_principal || {}), email: e.target.value })} /></div>
                                    <div>
                                        <Label className="text-xs">Canal de Origem</Label>
                                        <Select value={val("canal_origem")} onValueChange={(v) => setVal("canal_origem", v)}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {detailChannelOptions.map((value) => (
                                                    <SelectItem key={value} value={value}>{formatSlugLabel(value)}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div>
                                        <Label className="text-xs flex items-center gap-1">Origem do Lead <Tag className="h-3 w-3 text-amber-500" /></Label>
                                        <Select value={val("origem_lead")} onValueChange={(v) => setVal("origem_lead", v)}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {detailLeadOriginOptions.map((value) => (
                                                    <SelectItem key={value} value={value}>{formatSlugLabel(value)}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </div>
                            </section>

                            <section>
                                <Separator className="mb-3" />
                                <div className="flex items-start justify-between gap-3 mb-3">
                                    <div>
                                        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Qualificação</h4>
                                        {data.stage === "prospeccao" && (
                                            <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-1">
                                                Preencha estes campos no card para liberar o avanço até Projeto em Discussão.
                                            </p>
                                        )}
                                    </div>
                                </div>
                                <div className="space-y-3">
                                    <div>
                                        <Label className="text-xs">Tem Marca Própria?</Label>
                                        <div className="flex items-center gap-2 mt-1">
                                            <Switch checked={val("tem_marca_propria") || false} onCheckedChange={(v) => setVal("tem_marca_propria", v)} />
                                            <span className="text-sm">{val("tem_marca_propria") ? "Sim" : "Não"}</span>
                                        </div>
                                    </div>
                                    <div>
                                        <Label className="text-xs">Tem ANVISA?</Label>
                                        <Select value={temAnvisaValue} onValueChange={(v) => setVal("tem_anvisa", normalizeTemAnvisaValue(v))}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {ANVISA_OPTIONS.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div>
                                        <Label className="text-xs">Volume Estimado Mensal</Label>
                                        <Select value={val("volume_estimado_mensal")} onValueChange={(v) => setVal("volume_estimado_mensal", v)}>
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>{VOLUME_OPTIONS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
                                        </Select>
                                    </div>
                                    <div>
                                        <div className="flex items-center justify-between">
                                            <Label className="text-xs">Decisores</Label>
                                            <button
                                                type="button"
                                                className="text-[10px] text-primary hover:underline"
                                                onClick={() => setVal("decisores", [...decisores, { nome: "", cargo: "", contato: "" }])}
                                            >
                                                + Adicionar
                                            </button>
                                        </div>
                                        <div className="space-y-2 mt-1">
                                            {decisores.length === 0 && (
                                                <p className="text-[10px] text-amber-600">Adicione ao menos um decisor para concluir a qualificação.</p>
                                            )}
                                            {decisores.map((decisor, idx) => (
                                                <div key={idx} className="grid grid-cols-1 gap-2 rounded-md border border-border p-2">
                                                    <Input
                                                        className="h-8 text-xs"
                                                        placeholder="Nome do decisor"
                                                        value={decisor.nome || ""}
                                                        onChange={(e) => {
                                                            const next = [...decisores];
                                                            next[idx] = { ...next[idx], nome: e.target.value };
                                                            setVal("decisores", next);
                                                        }}
                                                    />
                                                    <Select
                                                        value={decisor.cargo || ""}
                                                        onValueChange={(v) => {
                                                            const next = [...decisores];
                                                            next[idx] = { ...next[idx], cargo: v };
                                                            setVal("decisores", next);
                                                        }}
                                                    >
                                                        <SelectTrigger className="h-8"><SelectValue placeholder="Cargo" /></SelectTrigger>
                                                        <SelectContent>
                                                            {detailCargoOptions.map((cargo) => (
                                                                <SelectItem key={cargo} value={cargo}>{formatSlugLabel(cargo)}</SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </Select>
                                                    <div className="flex gap-2">
                                                        <Input
                                                            className="h-8 text-xs"
                                                            placeholder="Contato"
                                                            value={decisor.contato || ""}
                                                            onChange={(e) => {
                                                                const next = [...decisores];
                                                                next[idx] = { ...next[idx], contato: e.target.value };
                                                                setVal("decisores", next);
                                                            }}
                                                        />
                                                        <Button
                                                            type="button"
                                                            variant="ghost"
                                                            size="sm"
                                                            className="shrink-0"
                                                            onClick={() => setVal("decisores", decisores.filter((_, decisorIndex) => decisorIndex !== idx))}
                                                        >
                                                            Remover
                                                        </Button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        <div className="flex items-center gap-2">
                                            <Switch
                                                checked={Boolean(fornecedorAtual.tem)}
                                                onCheckedChange={(checked) => setVal("fornecedor_atual", { ...fornecedorAtual, tem: checked, motivo_troca: checked ? fornecedorAtual.motivo_troca : "" })}
                                            />
                                            <Label className="text-xs">Possui fornecedor atual?</Label>
                                        </div>
                                        {fornecedorAtual.tem && (
                                            <Input
                                                className="h-8 text-xs"
                                                placeholder="Motivo da troca de fornecedor"
                                                value={fornecedorAtual.motivo_troca || ""}
                                                onChange={(e) => setVal("fornecedor_atual", { ...fornecedorAtual, motivo_troca: e.target.value })}
                                            />
                                        )}
                                    </div>
                                    <div><Label className="text-xs">Prazo / Urgência</Label><Input type="date" value={val("prazo_urgencia") || ""} onChange={(e) => setVal("prazo_urgencia", e.target.value)} /></div>
                                </div>
                            </section>

                            {/* Negociação — visible from stage >= negociacao */}
                            {stageIndex >= 3 && (
                                <section>
                                    <Separator className="mb-3" />
                                    <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Negociação</h4>
                                    <div className="space-y-3">
                                        <div>
                                            <Label className="text-xs">Valor Estimado do Projeto</Label>
                                            <CurrencyInput
                                                value={val("valor_estimado_projeto") || ""}
                                                currency={val("valor_estimado_projeto_currency") || "BRL"}
                                                onValueChange={(v) => setVal("valor_estimado_projeto", v)}
                                                onCurrencyChange={(c) => setVal("valor_estimado_projeto_currency", c)}
                                                className="mt-1"
                                            />
                                        </div>
                                        <div><Label className="text-xs">MOQ Negociado</Label><Input value={val("moq_negociado")} onChange={(e) => setVal("moq_negociado", e.target.value)} /></div>
                                        <div><Label className="text-xs">Condição de Pagamento</Label><Input value={val("condicao_pagamento")} onChange={(e) => setVal("condicao_pagamento", e.target.value)} /></div>
                                        <div><Label className="text-xs">Concorrentes Envolvidos</Label><Input value={(val("concorrentes_envolvidos") || []).join(", ")} onChange={(e) => setVal("concorrentes_envolvidos", e.target.value.split(",").map(s => s.trim()).filter(Boolean))} placeholder="Separados por vírgula" /></div>
                                    </div>
                                </section>
                            )}

                            {/* Fechado — visible from stage >= cliente_fechado */}
                            {stageIndex >= 4 && (
                                <section>
                                    <Separator className="mb-3" />
                                    <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Fechamento</h4>
                                    <div className="space-y-3">
                                        <div><Label className="text-xs">Data do Pedido</Label><Input type="date" value={val("data_pedido") || ""} onChange={(e) => setVal("data_pedido", e.target.value)} /></div>
                                        <div>
                                            <Label className="text-xs">Valor do Primeiro Pedido</Label>
                                            <CurrencyInput
                                                value={val("valor_primeiro_pedido") || ""}
                                                currency={val("valor_primeiro_pedido_currency") || "BRL"}
                                                onValueChange={(v) => setVal("valor_primeiro_pedido", v)}
                                                onCurrencyChange={(c) => setVal("valor_primeiro_pedido_currency", c)}
                                                className="mt-1"
                                            />
                                        </div>
                                        <div><Label className="text-xs">Previsão Segundo Pedido</Label><Input type="date" value={val("previsao_segundo_pedido") || ""} onChange={(e) => setVal("previsao_segundo_pedido", e.target.value)} /></div>
                                    </div>
                                </section>
                            )}

                            {/* Perdido */}
                            {data.stage === "cliente_perdido" && data.motivo_perda && (
                                <section>
                                    <Separator className="mb-3" />
                                    <h4 className="text-xs font-semibold text-red-500 uppercase tracking-wider mb-2">Motivo da Perda</h4>
                                    <p className="text-sm bg-red-50 dark:bg-red-950/30 p-3 rounded-md border border-red-200 dark:border-red-800">{data.motivo_perda}</p>
                                </section>
                            )}

                            {canEdit && Object.keys(editing).length > 0 && (
                                <div className="pt-3">
                                    <Button onClick={handleSave} disabled={saving} className="w-full">
                                        {saving ? "Salvando..." : "Salvar Alterações"}
                                    </Button>
                                </div>
                            )}
                            {isAdmin && (
                                <div className="pt-3">
                                    <Button
                                        type="button"
                                        variant="outline"
                                        className="w-full text-destructive hover:text-destructive border-destructive/40"
                                        onClick={() => onDelete?.(data)}
                                    >
                                        Excluir Cliente
                                    </Button>
                                </div>
                            )}
                        </div>
                    </TabsContent>

                    <TabsContent value="projetos" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3">
                        {!fullData ? (
                            <p className="text-sm text-muted-foreground">Carregando...</p>
                        ) : (fullData.projects || []).length === 0 ? (
                            <p className="text-sm text-muted-foreground">Nenhum projeto encontrado.</p>
                        ) : (
                            <div className="space-y-3">
                                {fullData.summary && (
                                    <div className="rounded-lg border border-border bg-muted/40 p-3 grid grid-cols-3 gap-3 text-center text-xs mb-4">
                                        <div><span className="block font-semibold text-base">{fullData.summary.projetos_ativos}</span>ativos</div>
                                        <div><span className="block font-semibold text-base">{fullData.summary.total_projetos}</span>total</div>
                                        <div><span className="block font-semibold text-base">{fullData.summary.total_amostras}</span>amostras</div>
                                    </div>
                                )}
                                {(fullData.projects || []).map((proj) => (
                                    <div key={proj.id} className="rounded-lg border border-border p-3 space-y-1">
                                        <p className="font-medium text-sm">{proj.nome_projeto}</p>
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <Badge variant="outline" className="text-[10px]">{proj.stage}</Badge>
                                            {proj.categoria && <Badge variant="secondary" className="text-[10px]">{proj.categoria}</Badge>}
                                        </div>
                                        {proj.created_at && <p className="text-[10px] text-muted-foreground">{new Date(proj.created_at).toLocaleDateString("pt-BR")}</p>}
                                    </div>
                                ))}
                            </div>
                        )}
                    </TabsContent>

                    <TabsContent value="pedidos" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3">
                        {!fullData ? (
                            <p className="text-sm text-muted-foreground">Carregando...</p>
                        ) : (fullData.orders || []).length === 0 ? (
                            <p className="text-sm text-muted-foreground">Nenhum pedido encontrado.</p>
                        ) : (
                            <div className="space-y-3">
                                {fullData.summary?.item_mais_pedido && (
                                    <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 text-xs">
                                        <span className="font-semibold">Item mais pedido:</span> {fullData.summary.item_mais_pedido}
                                    </div>
                                )}
                                {(fullData.orders || []).map((order) => (
                                    <div key={order.id} className="rounded-lg border border-border p-3 space-y-1">
                                        <div className="flex items-center justify-between">
                                            <p className="font-medium text-sm">{order.numero_pedido}</p>
                                            <Badge variant="outline" className="text-[10px]">{order.status}</Badge>
                                        </div>
                                        {order.total_pedido > 0 && (
                                            <p className="text-xs text-muted-foreground">
                                                R$ {Number(order.total_pedido).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                                            </p>
                                        )}
                                        {order.created_at && <p className="text-[10px] text-muted-foreground">{new Date(order.created_at).toLocaleDateString("pt-BR")}</p>}
                                    </div>
                                ))}
                            </div>
                        )}
                    </TabsContent>

                    <TabsContent value="contatos" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3">
                        <div className="space-y-4">
                            {data.contato_principal?.nome && (
                                <div className="rounded-lg border border-border p-3 space-y-1">
                                    <div className="flex items-center gap-2">
                                        <p className="font-medium text-sm">{data.contato_principal.nome}</p>
                                        {(data.contato_principal.cargo === "outro" ? data.contato_principal.cargo_custom : data.contato_principal.cargo) && (
                                            <Badge variant="secondary" className="text-[10px]">
                                                {data.contato_principal.cargo === "outro" ? data.contato_principal.cargo_custom : formatSlugLabel(data.contato_principal.cargo)}
                                            </Badge>
                                        )}
                                        <Badge className="text-[10px] bg-primary/10 text-primary border-primary/20">Principal</Badge>
                                    </div>
                                    {data.contato_principal.whatsapp && <p className="text-xs text-muted-foreground">{data.contato_principal.whatsapp}</p>}
                                    {data.contato_principal.email && <p className="text-xs text-muted-foreground">{data.contato_principal.email}</p>}
                                </div>
                            )}
                            {(data.contatos_adicionais || []).map((c, idx) => (
                                <div key={idx} className="rounded-lg border border-border p-3 space-y-1">
                                    <div className="flex items-center gap-2">
                                        <p className="font-medium text-sm">{c.nome || `Contato ${idx + 1}`}</p>
                                        {(c.cargo === "outro" ? c.cargo_custom : c.cargo) && (
                                            <Badge variant="secondary" className="text-[10px]">
                                                {c.cargo === "outro" ? c.cargo_custom : formatSlugLabel(c.cargo)}
                                            </Badge>
                                        )}
                                    </div>
                                    {c.whatsapp && <p className="text-xs text-muted-foreground">{c.whatsapp}</p>}
                                    {c.email && <p className="text-xs text-muted-foreground">{c.email}</p>}
                                </div>
                            ))}
                            {!data.contato_principal?.nome && (!data.contatos_adicionais || data.contatos_adicionais.length === 0) && (
                                <p className="text-sm text-muted-foreground">Nenhum contato cadastrado.</p>
                            )}
                        </div>
                    </TabsContent>

                    <TabsContent value="timeline" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3">
                        <div className="space-y-3">
                            {(data.historico_movimentacoes || []).slice().reverse().map((mov, idx) => (
                                <div key={idx} className="flex gap-3 items-start">
                                    <div className="mt-1 w-2 h-2 rounded-full bg-primary shrink-0" />
                                    <div>
                                        <p className="text-sm">
                                            <span className="font-medium">{STAGES.find(s => s.id === mov.de)?.label || mov.de}</span>
                                            <ChevronRight className="h-3 w-3 inline mx-1" />
                                            <span className="font-medium">{STAGES.find(s => s.id === mov.para)?.label || mov.para}</span>
                                        </p>
                                        <p className="text-xs text-muted-foreground">
                                            {mov.usuario} · {new Date(mov.data).toLocaleString("pt-BR")}
                                            {mov.is_regression && <span className="ml-1 text-amber-600 font-medium">(retroativa)</span>}
                                        </p>
                                        {mov.justificativa && (
                                            <p className="text-xs text-muted-foreground italic mt-0.5">"{mov.justificativa}"</p>
                                        )}
                                    </div>
                                </div>
                            ))}
                            {(!data.historico_movimentacoes || data.historico_movimentacoes.length === 0) && (
                                <p className="text-sm text-muted-foreground">Nenhuma movimentação registrada.</p>
                            )}
                        </div>
                    </TabsContent>
                </Tabs>
            </SheetContent>
        </Sheet>
    );
}
