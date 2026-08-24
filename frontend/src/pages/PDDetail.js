import React, { useState, useEffect, useCallback, useMemo } from "react";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { BACKEND_URL } from "@/lib/backend";
import { FieldHint } from "@/components/ui/FieldHint";
import { formatApiError } from "@/lib/formatError";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { indexToLetters } from "@/lib/letters";
import {
  ArrowLeft, FlaskConical, Clock, Plus, Trash2, CheckCircle2, XCircle,
  Loader2, ArrowRight, FileText, DollarSign, Beaker, Package, History,
  Eye, Download, Pencil, Save, X, ShieldCheck, Send, MessageSquare, Settings2,
  Bell, Hourglass, AlertTriangle, Sparkles, ClipboardList, ThumbsUp, ThumbsDown,
  CheckSquare, XSquare, Lock, Unlock, RefreshCw, TestTube, TrendingUp,
  Thermometer, Wind, Snowflake, Sun, ChevronUp, ChevronDown, Copy, Search,
  Building2, ShoppingCart, Layers, CheckCircle, Clock4, AlertCircle,
  GitBranch, Combine, ChevronRight, FlaskRound, ExternalLink
} from "lucide-react";

const STATUS_CONFIG = {
  OPEN: { label: "Aberto", color: "bg-blue-500/10 text-blue-600 border-blue-200", dotColor: "bg-blue-500" },
  IN_PROGRESS: { label: "Em Desenvolvimento", color: "bg-amber-500/10 text-amber-600 border-amber-200", dotColor: "bg-amber-500" },
  IN_TESTS: { label: "Em Testes", color: "bg-purple-500/10 text-purple-600 border-purple-200", dotColor: "bg-purple-500" },
  WAITING_APPROVAL: { label: "Aguardando Aprovação", color: "bg-orange-500/10 text-orange-600 border-orange-200", dotColor: "bg-orange-500" },
  APPROVED: { label: "Aprovado", color: "bg-green-500/10 text-green-600 border-green-200", dotColor: "bg-green-500" },
  COMPLETED: { label: "Concluído", color: "bg-emerald-500/10 text-emerald-700 border-emerald-200", dotColor: "bg-emerald-600" },
  REJECTED: { label: "Rejeitado", color: "bg-red-500/10 text-red-600 border-red-200", dotColor: "bg-red-500" },
};

const ALLOWED_TRANSITIONS = {
  OPEN: ["IN_PROGRESS"],
  IN_PROGRESS: ["IN_TESTS"],
  IN_TESTS: ["WAITING_APPROVAL"],
  WAITING_APPROVAL: ["APPROVED", "REJECTED"],
  APPROVED: ["COMPLETED"],
  REJECTED: ["IN_PROGRESS"],
  COMPLETED: [],
};

const BACKWARD_TRANSITIONS = {
  IN_PROGRESS: "OPEN",
  IN_TESTS: "IN_PROGRESS",
  WAITING_APPROVAL: "IN_TESTS",
  APPROVED: "WAITING_APPROVAL",
};

const TEST_STATUS_OPTIONS = ["PENDING", "RUNNING", "APPROVED", "FAILED"];
const DOC_TYPES = ["Ficha Técnica", "Laudo", "Especificação", "Briefing Cliente", "Outro"];

const REQUEST_TYPES = ["Produto Novo", "Reformulação", "Extensão de Linha", "Adequação Regulatória", "Outro"];
const CATEGORIES = ["Skincare", "Haircare", "Bodycare", "Perfumaria", "Maquiagem", "Higiene", "Outro"];
const PRIORITIES = ["Baixa", "Normal", "Alta", "Urgente"];

// Structured test fields per type
const TEST_FIELDS = {
  Estabilidade: [
    { key: "condicao", label: "Condição", placeholder: "Ex: 45°C / 90 dias" },
    { key: "aspecto", label: "Aspecto", placeholder: "Normal, separação, etc." },
    { key: "cor", label: "Cor", placeholder: "Inalterada, escurecida, etc." },
    { key: "odor", label: "Odor", placeholder: "Inalterado, alterado, etc." },
    { key: "observacoes", label: "Observações", placeholder: "Notas adicionais", multiline: true },
  ],
  pH: [
    { key: "valor_medido", label: "Valor Medido", placeholder: "Ex: 5.5" },
    { key: "faixa_aceitavel", label: "Faixa Aceitável", placeholder: "Ex: 5.0 - 6.0" },
    { key: "temperatura", label: "Temperatura (°C)", placeholder: "Ex: 25" },
    { key: "observacoes", label: "Observações", placeholder: "Notas adicionais", multiline: true },
  ],
  Viscosidade: [
    { key: "valor_medido", label: "Valor Medido", placeholder: "Ex: 15000" },
    { key: "unidade", label: "Unidade", placeholder: "Ex: cP, mPa.s" },
    { key: "spindle", label: "Spindle / Velocidade", placeholder: "Ex: S64 / 20 rpm" },
    { key: "temperatura", label: "Temperatura (°C)", placeholder: "Ex: 25" },
    { key: "observacoes", label: "Observações", placeholder: "Notas adicionais", multiline: true },
  ],
  Sensorial: [
    { key: "aspecto", label: "Aspecto", placeholder: "Creme, líquido, gel, etc." },
    { key: "cor", label: "Cor", placeholder: "Branca, translúcida, etc." },
    { key: "odor", label: "Odor", placeholder: "Agradável, suave, etc." },
    { key: "toque", label: "Toque", placeholder: "Sedoso, leve, pegajoso, etc." },
    { key: "espalhabilidade", label: "Espalhabilidade", placeholder: "Boa, excelente, etc." },
    { key: "observacoes", label: "Observações", placeholder: "Notas adicionais", multiline: true },
  ],
  Compatibilidade: [
    { key: "material_testado", label: "Material Testado", placeholder: "Ex: PET, Alumínio, PP" },
    { key: "tempo_dias", label: "Tempo (dias)", placeholder: "Ex: 30, 60, 90" },
    { key: "resultado", label: "Resultado", placeholder: "Compatível, incompatível, etc." },
    { key: "observacoes", label: "Observações", placeholder: "Notas adicionais", multiline: true },
  ],
};

const normalizeLookup = (value = "") =>
  String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase();

const toFiniteNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

function buildSupplierLookup(fornecedores = []) {
  const byId = new Map();
  const byName = new Map();

  fornecedores.forEach((fornecedor) => {
    if (fornecedor?.id) {
      byId.set(fornecedor.id, fornecedor);
    }
    [fornecedor?.razao_social, fornecedor?.nome_fantasia, fornecedor?.codigo_interno].forEach((candidate) => {
      const key = normalizeLookup(candidate);
      if (key && !byName.has(key)) {
        byName.set(key, fornecedor);
      }
    });
  });

  return { byId, byName };
}

function normalizeSupplierOption(rawSupplier, lookup) {
  if (!rawSupplier) return null;

  const rawId = rawSupplier.fornecedor_id || rawSupplier.id || "";
  const rawName =
    rawSupplier.fornecedor_nome ||
    rawSupplier.nome ||
    rawSupplier.razao_social ||
    rawSupplier.nome_fantasia ||
    "";
  const matched =
    (rawId && lookup.byId.get(rawId)) ||
    lookup.byName.get(normalizeLookup(rawName)) ||
    {};

  const razaoSocial =
    matched.razao_social ||
    rawSupplier.razao_social ||
    rawSupplier.fornecedor_nome ||
    rawSupplier.nome ||
    matched.nome_fantasia ||
    rawSupplier.nome_fantasia ||
    "";

  if (!razaoSocial.trim()) return null;

  return {
    id: rawId || rawSupplier.codigo || rawSupplier.codigo_fornecedor || normalizeLookup(razaoSocial),
    nome: razaoSocial,
    razao_social: matched.razao_social || razaoSocial,
    nome_fantasia: matched.nome_fantasia || rawSupplier.nome_fantasia || "",
    codigo: rawSupplier.codigo || rawSupplier.codigo_fornecedor || matched.codigo_interno || "",
    moeda: String(rawSupplier.moeda || "BRL").toUpperCase(),
    preco_rs_kg:
      toFiniteNumber(rawSupplier.preco_rs_kg) ??
      toFiniteNumber(rawSupplier.preco_por_unidade) ??
      toFiniteNumber(rawSupplier.custo_referencia),
    unidade: rawSupplier.unidade || rawSupplier.unidade_compra || "kg",
    status:
      rawSupplier.status_homologacao ||
      rawSupplier.status ||
      matched?.homologacao?.status ||
      "",
  };
}

function dedupeSupplierOptions(suppliers = []) {
  const byKey = new Map();

  suppliers.forEach((supplier) => {
    const normalized = normalizeSupplierOption(supplier, { byId: new Map(), byName: new Map() }) || supplier;
    const key = `${normalized.id || ""}:${normalizeLookup(normalized.razao_social || normalized.nome)}`;
    if (!key || key === ":") return;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, normalized);
      return;
    }
    const existingPrice = toFiniteNumber(existing.preco_rs_kg);
    const nextPrice = toFiniteNumber(normalized.preco_rs_kg);
    if (existingPrice === null && nextPrice !== null) {
      byKey.set(key, { ...existing, ...normalized });
    }
  });

  return [...byKey.values()].sort((a, b) => {
    const priceA = toFiniteNumber(a.preco_rs_kg);
    const priceB = toFiniteNumber(b.preco_rs_kg);
    if (priceA !== null && priceB !== null && priceA !== priceB) return priceA - priceB;
    if (priceA !== null && priceB === null) return -1;
    if (priceA === null && priceB !== null) return 1;
    return (a.razao_social || a.nome || "").localeCompare(b.razao_social || b.nome || "", "pt-BR");
  });
}

function buildSupplierDirectoryOptions(fornecedores = []) {
  const lookup = buildSupplierLookup(fornecedores);
  return dedupeSupplierOptions(
    fornecedores
      .map((fornecedor) =>
        normalizeSupplierOption(
          {
            id: fornecedor.id,
            razao_social: fornecedor.razao_social,
            nome_fantasia: fornecedor.nome_fantasia,
            codigo: fornecedor.codigo_interno,
            status: fornecedor?.homologacao?.status,
          },
          lookup,
        ),
      )
      .filter(Boolean),
  );
}

function buildPdIngredientOptions({ catalog = [], materiais = [], homologacaoMps = [], fornecedores = [] }) {
  const supplierLookup = buildSupplierLookup(fornecedores);
  const optionsByKey = new Map();

  const ensureOption = ({
    key,
    nome,
    inci = "",
    codigo_interno = "",
    unidade = "kg",
    categoria = "",
    catalog_id = "",
    source = "",
    preco_rs_kg = null,
  }) => {
    if (!key || !nome) return null;
    const existing = optionsByKey.get(key) || {
      id: catalog_id || key,
      option_key: key,
      nome,
      inci: "",
      codigo_interno: "",
      unidade: "kg",
      categoria: "",
      catalog_id: "",
      preco_rs_kg: null,
      fornecedores: [],
      source_tags: [],
    };

    if (!existing.nome && nome) existing.nome = nome;
    if (!existing.inci && inci) existing.inci = inci;
    if (!existing.codigo_interno && codigo_interno) existing.codigo_interno = codigo_interno;
    if (!existing.categoria && categoria) existing.categoria = categoria;
    if ((!existing.unidade || existing.unidade === "kg") && unidade) existing.unidade = unidade;
    if (!existing.catalog_id && catalog_id) {
      existing.catalog_id = catalog_id;
      existing.id = catalog_id;
    }
    if (existing.preco_rs_kg === null && preco_rs_kg !== null) {
      existing.preco_rs_kg = preco_rs_kg;
    }
    if (source && !existing.source_tags.includes(source)) {
      existing.source_tags.push(source);
    }

    optionsByKey.set(key, existing);
    return existing;
  };

  catalog.forEach((item) => {
    const option = ensureOption({
      key: normalizeLookup(item.nome || item.inci || item.codigo_interno),
      nome: item.nome || item.inci || item.codigo_interno,
      inci: item.inci || "",
      codigo_interno: item.codigo_interno || "",
      unidade: item.unidade || "kg",
      categoria: item.categoria || "Catálogo",
      catalog_id: item.id || "",
      source: "catalogo",
      preco_rs_kg: toFiniteNumber(item.preco_rs_kg),
    });
    if (!option) return;
    (item.fornecedores || []).forEach((supplier) => {
      const normalized = normalizeSupplierOption(
        {
          nome: supplier.nome,
          codigo: supplier.codigo,
          preco_rs_kg: supplier.preco_rs_kg,
          moeda: supplier.moeda,
          unidade: item.unidade || "kg",
        },
        supplierLookup,
      );
      if (normalized) option.fornecedores.push(normalized);
    });
  });

  materiais.forEach((item) => {
    const option = ensureOption({
      key: normalizeLookup(item.nome || item.codigo_interno),
      nome: item.nome || item.codigo_interno,
      codigo_interno: item.codigo_interno || "",
      unidade: item.unidade_compra || item.unidade_estoque || "kg",
      categoria: item.subtipo || "Cadastro MP",
      source: "materiais",
    });
    if (!option) return;
    (item.fornecedores || []).forEach((supplier) => {
      const normalized = normalizeSupplierOption(
        {
          fornecedor_id: supplier.fornecedor_id,
          fornecedor_nome: supplier.fornecedor_nome,
          codigo_fornecedor: supplier.codigo_fornecedor,
          preco_por_unidade: supplier.preco_por_unidade,
          moeda: supplier.moeda,
          unidade_compra: supplier.unidade_compra || item.unidade_compra || item.unidade_estoque || "kg",
          status_homologacao: supplier.status_homologacao,
        },
        supplierLookup,
      );
      if (normalized) option.fornecedores.push(normalized);
    });
  });

  homologacaoMps.forEach((item) => {
    const option = ensureOption({
      key: normalizeLookup(item.nome || item.codigo_interno || item.inci),
      nome: item.nome || item.inci || item.codigo_interno,
      inci: item.inci || "",
      codigo_interno: item.codigo_interno || "",
      unidade: item.unidade || "kg",
      categoria: item.funcao || "Homologação",
      source: "homologacao",
      preco_rs_kg: toFiniteNumber(item.custo_referencia),
    });
    if (!option) return;
    if (item.fornecedor_id || item.fornecedor_nome) {
      const normalized = normalizeSupplierOption(
        {
          fornecedor_id: item.fornecedor_id,
          fornecedor_nome: item.fornecedor_nome,
          custo_referencia: item.custo_referencia,
          moeda: "BRL",
          unidade: item.unidade || "kg",
          status: item.status,
        },
        supplierLookup,
      );
      if (normalized) option.fornecedores.push(normalized);
    }
  });

  return [...optionsByKey.values()]
    .map((option) => ({
      ...option,
      fornecedores: dedupeSupplierOptions(option.fornecedores),
    }))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
}

function findSupplierByName(suppliers = [], value = "") {
  const target = normalizeLookup(value);
  if (!target) return null;
  return (
    suppliers.find((supplier) => normalizeLookup(supplier.razao_social || supplier.nome) === target) ||
    suppliers.find((supplier) => normalizeLookup(supplier.nome_fantasia) === target) ||
    null
  );
}

function usePdMaterialLibrary() {
  const [catalog, setCatalog] = useState([]);
  const [materiais, setMateriais] = useState([]);
  const [homologacaoMps, setHomologacaoMps] = useState([]);
  const [fornecedores, setFornecedores] = useState([]);

  useEffect(() => {
    let active = true;

    (async () => {
      const [catalogResult, materiaisResult, homologacaoResult, fornecedoresResult] = await Promise.allSettled([
        api.get("/pd/catalog"),
        api.get("/cadastros/materiais", { params: { tipo2: "MP", status: "ativo" } }),
        api.get("/pd/homologacao/mps", { params: { tipo_mp: "FORMULACAO" } }),
        api.get("/compras/fornecedores", { params: { limit: 500 } }),
      ]);

      if (!active) return;

      setCatalog(
        catalogResult.status === "fulfilled" && Array.isArray(catalogResult.value?.data)
          ? catalogResult.value.data
          : [],
      );
      setMateriais(
        materiaisResult.status === "fulfilled" && Array.isArray(materiaisResult.value?.data?.materiais)
          ? materiaisResult.value.data.materiais
          : [],
      );
      setHomologacaoMps(
        homologacaoResult.status === "fulfilled" && Array.isArray(homologacaoResult.value?.data)
          ? homologacaoResult.value.data
          : [],
      );
      setFornecedores(
        fornecedoresResult.status === "fulfilled" && Array.isArray(fornecedoresResult.value?.data?.fornecedores)
          ? fornecedoresResult.value.data.fornecedores
          : [],
      );
    })();

    return () => {
      active = false;
    };
  }, []);

  const supplierOptions = useMemo(() => buildSupplierDirectoryOptions(fornecedores), [fornecedores]);
  const ingredientOptions = useMemo(
    () => buildPdIngredientOptions({ catalog, materiais, homologacaoMps, fornecedores }),
    [catalog, materiais, homologacaoMps, fornecedores],
  );

  const getIngredientOption = useCallback(
    (ingredientName) => ingredientOptions.find((item) => item.option_key === normalizeLookup(ingredientName)) || null,
    [ingredientOptions],
  );

  const getSuppliersForIngredient = useCallback(
    (ingredientName) => {
      const ingredient = getIngredientOption(ingredientName);
      if (ingredient?.fornecedores?.length) {
        return ingredient.fornecedores;
      }
      return supplierOptions;
    },
    [getIngredientOption, supplierOptions],
  );

  return {
    ingredientOptions,
    supplierOptions,
    getIngredientOption,
    getSuppliersForIngredient,
  };
}

export default function PDDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user: authUser } = useAuth();
  const canEdit = authUser && ["admin", "gestor", "formulador", "lider_pd", "engenharia_produto"].includes(authUser.role);
  const canApproveCommercial = authUser && ["admin", "vendedor", "sales_ops", "sucesso_cliente"].includes(authUser.role);
  const canManageApproval = Boolean(canEdit || canApproveCommercial);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");
  const [showBackwardDialog, setShowBackwardDialog] = useState(false);
  const [backwardJustification, setBackwardJustification] = useState("");
  const [showLinkCRM, setShowLinkCRM] = useState(false);
  const [crmProjectSearch, setCrmProjectSearch] = useState("");
  const [crmProjects, setCrmProjects] = useState([]);
  const [crmSearchLoading, setCrmSearchLoading] = useState(false);
  const [linkingCRM, setLinkingCRM] = useState(false);
  const [selectedCRMProject, setSelectedCRMProject] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await api.get(`/pd/requests/${id}/full`);
      setData(res.data);
    } catch (err) {
      toast.error("Erro ao carregar dados");
      navigate("/pd");
    } finally {
      setLoading(false);
    }
  }, [id, navigate]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const searchCRMProjects = useCallback(async (q) => {
    if (!q || q.length < 2) { setCrmProjects([]); return; }
    setCrmSearchLoading(true);
    try {
      const { data: d } = await api.get("/crm/projects", { params: { search: q, limit: 10 } });
      setCrmProjects(Array.isArray(d.items || d) ? (d.items || d) : []);
    } catch { setCrmProjects([]); } finally { setCrmSearchLoading(false); }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => searchCRMProjects(crmProjectSearch), 300);
    return () => clearTimeout(t);
  }, [crmProjectSearch, searchCRMProjects]);

  const handleStatusChange = async (newStatus, { isBackward = false, comment = "" } = {}) => {
    if (!isBackward) {
      const blockingTasks = (data?.blocking_tasks || []).filter(t =>
        !t.blocks_stages?.length || t.blocks_stages.includes(newStatus)
      );
      if (blockingTasks.length > 0) {
        const titles = blockingTasks.slice(0, 3).map(t => `• ${t.title}`).join("\n");
        const confirmed = window.confirm(
          `Existem ${blockingTasks.length} tarefa(s) bloqueante(s):\n${titles}\n\nDeseja avançar mesmo assim?`
        );
        if (!confirmed) return;
      }
    }
    try {
      const response = await api.put(`/pd/requests/${id}/status`, { new_status: newStatus, is_backward: isBackward, comment: comment || undefined });
      toast.success(isBackward ? "Etapa retrocedida!" : "Status atualizado!");
      const skuCreated = response?.data?.sku_created;
      if (newStatus === "APPROVED" && skuCreated) {
        if (skuCreated.blocked) {
          toast.warning(skuCreated.reason || "SKU não pôde ser gerado.");
        } else if (skuCreated.codigo_interno) {
          toast.success(`SKU gerado: ${skuCreated.codigo_interno}`);
        }
      }
      fetchData();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao alterar status");
    }
  };

  const handleCommercialReject = () => {
    const comment = window.prompt("Anotações para o retrabalho no P&D:");
    if (!comment || comment.trim().length < 5) {
      toast.error("Informe as anotações do retrabalho");
      return;
    }
    handleStatusChange("REJECTED", { comment });
  };

  const handleBackward = async () => {
    if (!backwardJustification.trim() || backwardJustification.trim().length < 10) {
      toast.error("Justificativa deve ter no mínimo 10 caracteres");
      return;
    }
    const currentStatus = data?.request?.status;
    const targetStatus = BACKWARD_TRANSITIONS[currentStatus];
    if (!targetStatus) return;
    await handleStatusChange(targetStatus, { isBackward: true, comment: backwardJustification });
    setShowBackwardDialog(false);
    setBackwardJustification("");
  };

  const downloadFichaTecnica = async () => {
    try {
      const response = await api.get(`/pd/requests/${id}/ficha-tecnica`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = `ficha_tecnica_${data?.request?.project_name?.replace(/\s/g, '_') || 'pd'}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Ficha técnica gerada!");
    } catch (err) {
      toast.error("Erro ao gerar ficha técnica");
    }
  };

  if (loading || !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const { request: req, development: dev, formulas, tests, samples, approval, costs, documents, history, client_info, formula_cost_data, cost_versions, lab_results, updates, pending } = data;
  const statusConfig = STATUS_CONFIG[req.status] || { label: req.status, color: "bg-gray-500/10 text-gray-600 border-gray-200", dotColor: "bg-gray-400" };
  const allowedNext = ALLOWED_TRANSITIONS[req.status] || [];
  const hasDev = !!dev;
  const pendingCount = (pending || []).filter(p => p.status === "pendente").length;
  const isInternalResearch = !!req.is_internal_research;
  const canViewCommercial = authUser && ["admin", "compras", "vendedor", "sales_ops", "sucesso_cliente"].includes(authUser.role);
  const canFinalizeCommercialCost = authUser && ["admin", "vendedor", "sales_ops", "sucesso_cliente"].includes(authUser.role);
  const canLinkToCRM = authUser && ["admin", "lider_pd", "formulador", "engenharia_produto", "vendedor", "sales_ops"].includes(authUser.role);

  const linkToCRM = async () => {
    if (!selectedCRMProject) return toast.error("Selecione um projeto CRM");
    setLinkingCRM(true);
    try {
      await api.put(`/pd/requests/${id}/link-to-crm`, {
        crm_project_id: selectedCRMProject.id,
        crm_client_id: selectedCRMProject.client_id || selectedCRMProject.crm_client_id,
        crm_client_name: selectedCRMProject.client_name || selectedCRMProject.crm_client_name || "",
      });
      toast.success("Pesquisa vinculada ao projeto CRM!");
      setShowLinkCRM(false);
      fetchData();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao vincular"); }
    finally { setLinkingCRM(false); }
  };

  const canDownloadTechSheet = authUser && ["admin", "lider_pd", "formulador", "qa", "engenharia_produto", "pcp", "supervisor", "vendedor", "sales_ops"].includes(authUser.role);

  const downloadTechSheet = async () => {
    if (!req.crm_sample_id) return toast.error("Amostra CRM não vinculada");
    try {
      const response = await api.get(`/pd/samples/${req.crm_sample_id}/tech-sheet.pdf`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.download = `ficha_tecnica_${req.project_name?.replace(/\s/g, "_") || "pd"}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Ficha técnica gerada (sem valores monetários)!");
    } catch (err) { toast.error("Erro ao gerar ficha técnica"); }
  };

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-6xl mx-auto p-6">
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-start gap-3">
            <Button variant="ghost" size="icon" onClick={() => navigate("/pd")} className="mt-0.5">
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h1 className="text-xl font-bold flex items-center gap-2">
                <FlaskConical className="h-5 w-5" />
                {req.project_name}
              </h1>
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                <Badge className={statusConfig.color}>{statusConfig.label}</Badge>
                <span className="text-xs text-muted-foreground">{req.request_type}</span>
                {req.client_name && <span className="text-xs text-muted-foreground">• {req.client_name}</span>}
                {req.priority && (
                  <Badge variant="outline" className="text-[10px]">{req.priority}</Badge>
                )}
                {isInternalResearch && (
                  <Badge className="bg-purple-500/20 text-purple-700 dark:text-purple-300 border-purple-300 text-[10px] gap-1">
                    <Sparkles className="h-3 w-3" /> Pesquisa Interna
                  </Badge>
                )}
                {pendingCount > 0 && (
                  <Badge className="bg-amber-500/20 text-amber-700 dark:text-amber-300 border-amber-300 text-[10px] gap-1">
                    <Hourglass className="h-3 w-3" /> {pendingCount} pendência(s)
                  </Badge>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap justify-end">
            {hasDev && (
              <Button size="sm" variant="outline" onClick={downloadFichaTecnica} className="gap-1.5">
                <Download className="h-3.5 w-3.5" />
                Ficha Técnica PDF
              </Button>
            )}
            {hasDev && req.crm_sample_id && canDownloadTechSheet && (
              <Button size="sm" variant="outline" onClick={downloadTechSheet} className="gap-1.5 border-sky-300 text-sky-700 hover:bg-sky-50">
                <FileText className="h-3.5 w-3.5" />
                Ficha Técnica (sem custos)
              </Button>
            )}
            {isInternalResearch && canLinkToCRM && !req.crm_project_id && (
              <Button size="sm" variant="outline" onClick={() => setShowLinkCRM(true)} className="gap-1.5 border-purple-300 text-purple-700 hover:bg-purple-50">
                <GitBranch className="h-3.5 w-3.5" />
                Vincular a projeto CRM
              </Button>
            )}
            {req.crm_project_id && (
              <Badge className="bg-purple-500/10 text-purple-700 border-purple-300 text-[10px] gap-1">
                <GitBranch className="h-3 w-3" /> Vinculado ao CRM
              </Badge>
            )}
            {canEdit && BACKWARD_TRANSITIONS[req.status] && (
              <Button size="sm" variant="outline" onClick={() => { setBackwardJustification(""); setShowBackwardDialog(true); }} className="gap-1.5 text-muted-foreground border-dashed">
                <ArrowLeft className="h-3.5 w-3.5" /> Retroceder
              </Button>
            )}
            {canEdit && allowedNext
              .filter(ns => !(req.status === "WAITING_APPROVAL" && ["APPROVED", "REJECTED"].includes(ns)))
              .map(ns => {
                const isEntrega = req.status === "IN_TESTS" && ns === "WAITING_APPROVAL";
                const label = isEntrega ? "Entregar ao Comercial" : STATUS_CONFIG[ns]?.label;
                const Icon = ns === "REJECTED" ? XCircle : isEntrega ? Send : ArrowRight;
                const handleClick = () => handleStatusChange(ns);
                return (
                  <Button key={ns} size="sm"
                    variant={ns === "REJECTED" ? "destructive" : "default"}
                    onClick={handleClick}
                    className="gap-1.5">
                    <Icon className="h-3.5 w-3.5" />{label}
                  </Button>
                );
              })
            }
            {/* Botões de aprovação comercial — visíveis apenas para roles comerciais */}
            {canApproveCommercial && req.status === "WAITING_APPROVAL" && (
              <>
                <Button size="sm" variant="destructive" onClick={handleCommercialReject} className="gap-1.5">
                  <XCircle className="h-3.5 w-3.5" /> Reprovar
                </Button>
                <Button size="sm" className="gap-1.5 bg-green-600 hover:bg-green-700 text-white" onClick={() => handleStatusChange("APPROVED")}>
                  <CheckCircle2 className="h-3.5 w-3.5" /> Aprovar
                </Button>
              </>
            )}
          </div>
        </div>

          {/* Banner: aguardando aprovação comercial */}
          {req.status === "WAITING_APPROVAL" && (
            <div className="mt-4 flex items-start gap-3 rounded-lg border border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-950/30 p-3">
              <Send className="h-4 w-4 text-orange-600 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-orange-800 dark:text-orange-200">
                  Aguardando aprovação comercial
                </p>
                <p className="text-xs text-orange-700 dark:text-orange-300 mt-0.5">
                  {canApproveCommercial
                    ? "Use os botões acima para aprovar ou reprovar esta formulação."
                    : "O responsável comercial (vendedor / sales_ops) deve aprovar para prosseguir."}
                </p>
              </div>
            </div>
          )}

          {/* Banner: próximo passo após aprovação */}
          {(req.status === "APPROVED" || req.status === "COMPLETED") && (
            <div className="mt-4 flex items-start gap-3 rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/30 p-3">
              <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-green-800 dark:text-green-200">
                  {req.status === "APPROVED" ? "Amostra aprovada — próximo passo: Kickoff" : "P&D Concluído"}
                </p>
                {req.status === "APPROVED" && (
                  <p className="text-xs text-green-700 dark:text-green-300 mt-0.5">
                    Avance o <strong>Projeto CRM</strong> para o estágio <strong>"Pedido Aprovado"</strong> para criar o Kickoff automaticamente.
                  </p>
                )}
              </div>
              {req.crm_project_id && (
                <Button size="sm" variant="outline" className="shrink-0 border-green-300 text-green-700 hover:bg-green-100 gap-1.5" onClick={() => navigate("/crm/projects")}>
                  <ExternalLink className="h-3.5 w-3.5" /> Ir para Projetos CRM
                </Button>
              )}
            </div>
          )}

          {/* PD-17: Link to CRM modal */}
          {showLinkCRM && (
            <Dialog open onOpenChange={(open) => !open && setShowLinkCRM(false)}>
              <DialogContent className="w-[calc(100vw-2rem)] max-w-lg max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <GitBranch className="h-4 w-4 text-purple-500" /> Vincular a Projeto CRM
                  </DialogTitle>
                  <DialogDescription>
                    Associe esta pesquisa interna a um projeto existente no CRM Comercial.
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-3">
                  <div>
                    <Label>Buscar projeto CRM</Label>
                    <Input
                      value={crmProjectSearch}
                      onChange={e => { setCrmProjectSearch(e.target.value); setSelectedCRMProject(null); }}
                      placeholder="Nome do projeto ou cliente..."
                      className="mt-1"
                    />
                  </div>
                  {crmSearchLoading && <p className="text-xs text-muted-foreground flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Buscando...</p>}
                  {crmProjects.length > 0 && (
                    <div className="border rounded-md divide-y max-h-48 overflow-y-auto">
                      {crmProjects.map(p => (
                        <button
                          key={p.id}
                          onClick={() => setSelectedCRMProject(p)}
                          className={`w-full flex items-start gap-2 p-2.5 text-left hover:bg-muted/50 transition-colors text-sm ${selectedCRMProject?.id === p.id ? "bg-primary/10 border-l-2 border-primary" : ""}`}
                        >
                          <div className="flex-1 min-w-0">
                            <p className="font-medium truncate">{p.name || p.nome_projeto || p.produto}</p>
                            <p className="text-xs text-muted-foreground truncate">{p.client_name || p.cliente}</p>
                          </div>
                          {selectedCRMProject?.id === p.id && <CheckCircle2 className="h-4 w-4 text-primary shrink-0 mt-0.5" />}
                        </button>
                      ))}
                    </div>
                  )}
                  {selectedCRMProject && (
                    <div className="p-2 rounded border border-primary/30 bg-primary/5 text-sm">
                      <span className="font-medium">Selecionado:</span> {selectedCRMProject.name || selectedCRMProject.nome_projeto} — {selectedCRMProject.client_name || selectedCRMProject.cliente}
                    </div>
                  )}
                </div>
                <DialogFooter>
                  <Button variant="ghost" onClick={() => setShowLinkCRM(false)}>Cancelar</Button>
                  <Button onClick={linkToCRM} disabled={!selectedCRMProject || linkingCRM} className="gap-1.5">
                    {linkingCRM ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitBranch className="h-3.5 w-3.5" />}
                    Vincular
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          )}

          {showBackwardDialog && (
            <Dialog open onOpenChange={(open) => !open && setShowBackwardDialog(false)}>
              <DialogContent className="w-[calc(100vw-2rem)] max-w-md max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <ArrowLeft className="h-4 w-4 text-amber-500" /> Retroceder Etapa
                  </DialogTitle>
                  <DialogDescription>
                    De <strong>{STATUS_CONFIG[req.status]?.label}</strong> → <strong>{STATUS_CONFIG[BACKWARD_TRANSITIONS[req.status]]?.label}</strong>. Justificativa obrigatória.
                  </DialogDescription>
                </DialogHeader>
                <div>
                  <Label>Justificativa <span className="text-red-500">*</span></Label>
                  <Textarea
                    value={backwardJustification}
                    onChange={e => setBackwardJustification(e.target.value)}
                    placeholder="Descreva o motivo do retrocesso (mínimo 10 caracteres)..."
                    rows={3}
                    className="mt-1"
                  />
                  <p className="text-[11px] text-muted-foreground mt-1">{backwardJustification.length} / 10 mín.</p>
                </div>
                <DialogFooter>
                  <Button variant="ghost" onClick={() => setShowBackwardDialog(false)}>Cancelar</Button>
                  <Button variant="outline" onClick={handleBackward} disabled={backwardJustification.trim().length < 10} className="gap-1.5">
                    <ArrowLeft className="h-3.5 w-3.5" /> Confirmar Retrocesso
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          )}
        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="mb-4 flex-wrap h-auto gap-1">
            <TabsTrigger value="overview" className="gap-1.5"><Eye className="h-3.5 w-3.5" />Overview</TabsTrigger>
            <TabsTrigger value="formula" className="gap-1.5"><Beaker className="h-3.5 w-3.5" />Manipulação</TabsTrigger>
            <TabsTrigger value="tests" className="gap-1.5"><FlaskConical className="h-3.5 w-3.5" />Testes</TabsTrigger>
            <TabsTrigger value="samples" className="gap-1.5"><Package className="h-3.5 w-3.5" />Amostras</TabsTrigger>
            <TabsTrigger value="ficha_tecnica" className="gap-1.5"><ClipboardList className="h-3.5 w-3.5" />Ficha Técnica</TabsTrigger>
            <TabsTrigger value="updates" className="gap-1.5 relative">
              <Bell className="h-3.5 w-3.5" />Atualizações
              {pendingCount > 0 && (
                <span className="ml-1 inline-flex items-center justify-center px-1.5 min-w-[18px] h-[18px] text-[10px] font-bold rounded-full bg-amber-500 text-white">
                  {pendingCount}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="costs" className="gap-1.5"><DollarSign className="h-3.5 w-3.5" />Custos P&D</TabsTrigger>
            {canViewCommercial && (
              <TabsTrigger value="comercial" className="gap-1.5"><Building2 className="h-3.5 w-3.5" />Comercial</TabsTrigger>
            )}
            <TabsTrigger value="documents" className="gap-1.5"><FileText className="h-3.5 w-3.5" />Documentos</TabsTrigger>
            <TabsTrigger value="live_docs" className="gap-1.5" data-testid="tab-live-docs">
              <ShieldCheck className="h-3.5 w-3.5" />Documentos Vivos
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <ErrorBoundary label="Overview" resetKey={req.id}>
              <OverviewTab req={req} dev={dev} formulas={formulas} tests={tests} samples={samples} approval={approval} costs={costs} history={history} onRefresh={fetchData} hasDev={hasDev} clientInfo={client_info} canEdit={canEdit} canApproveCommercial={canApproveCommercial} canManageApproval={canManageApproval} onCommercialApprove={() => handleStatusChange("APPROVED")} onCommercialReject={handleCommercialReject} formulaCostData={formula_cost_data} setActiveTab={setActiveTab} documents={documents} updates={updates} pending={pending} canViewCommercial={canViewCommercial} labResults={lab_results} />
            </ErrorBoundary>
          </TabsContent>

          <TabsContent value="formula">
            <ErrorBoundary label="Manipulação" resetKey={req.id}>
              {hasDev ? (
                <FormulaTab devId={dev.id} formulas={formulas} onRefresh={fetchData} canEdit={canEdit} clientInfo={client_info} req={req} />
              ) : (
                <NeedsDev onAction={() => handleStatusChange("IN_PROGRESS")} status={req.status} canEdit={canEdit} />
              )}
            </ErrorBoundary>
          </TabsContent>

          <TabsContent value="tests">
            <ErrorBoundary label="Testes" resetKey={req.id}>
              {hasDev ? (
                <TestsTab devId={dev.id} labResults={lab_results} onRefresh={fetchData} canEdit={canEdit} reqId={req.id} />
              ) : (
                <NeedsDev onAction={() => handleStatusChange("IN_PROGRESS")} status={req.status} canEdit={canEdit} />
              )}
            </ErrorBoundary>
          </TabsContent>

          <TabsContent value="samples">
            <ErrorBoundary label="Amostras" resetKey={req.id}>
              {hasDev ? (
                <SamplesTab devId={dev.id} samples={samples} formulas={formulas} onRefresh={fetchData} canEdit={canEdit} productName={req.project_name || ""} />
              ) : (
                <NeedsDev onAction={() => handleStatusChange("IN_PROGRESS")} status={req.status} canEdit={canEdit} />
              )}
            </ErrorBoundary>
          </TabsContent>

          <TabsContent value="ficha_tecnica">
            <ErrorBoundary label="Ficha Técnica" resetKey={req.id}>
              <FichaTecnicaTab reqId={req.id} formulas={formulas} req={req} dev={dev} canEdit={canEdit} labResults={lab_results} />
            </ErrorBoundary>
          </TabsContent>

          <TabsContent value="updates">
            <ErrorBoundary label="Updates" resetKey={req.id}>
              <UpdatesTab reqId={req.id} updates={updates || []} pending={pending || []} onRefresh={fetchData} canEdit={canEdit} />
            </ErrorBoundary>
          </TabsContent>

          <TabsContent value="costs">
            <ErrorBoundary label="Custos P&D" resetKey={req.id}>
              {hasDev ? (
                <CostsTab devId={dev.id} costVersions={cost_versions} formulas={formulas} formulaCostData={formula_cost_data} onRefresh={fetchData} canEdit={canEdit} canViewCommercial={canViewCommercial} />
              ) : (
                <NeedsDev onAction={() => handleStatusChange("IN_PROGRESS")} status={req.status} canEdit={canEdit} />
              )}
            </ErrorBoundary>
          </TabsContent>

          {canViewCommercial && (
            <TabsContent value="comercial">
              <ErrorBoundary label="Comercial" resetKey={req.id}>
                {hasDev ? (
                  <ComercialTab devId={dev.id} costVersions={cost_versions} formulaCostData={formula_cost_data} onRefresh={fetchData} canFinalize={canFinalizeCommercialCost} />
                ) : (
                  <NeedsDev onAction={() => handleStatusChange("IN_PROGRESS")} status={req.status} canEdit={canEdit} />
                )}
              </ErrorBoundary>
            </TabsContent>
          )}

          <TabsContent value="documents">
            <ErrorBoundary label="Documentos" resetKey={req.id}>
              {hasDev ? (
                <DocumentsTab devId={dev.id} documents={documents} onRefresh={fetchData} canEdit={canEdit} />
              ) : (
                <NeedsDev onAction={() => handleStatusChange("IN_PROGRESS")} status={req.status} canEdit={canEdit} />
              )}
            </ErrorBoundary>
          </TabsContent>

          <TabsContent value="live_docs">
            <ErrorBoundary label="Documentos Vivos" resetKey={req.id}>
              <LiveDocumentsTab reqId={req.id} req={req} />
            </ErrorBoundary>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

/* ============ NEEDS DEV PLACEHOLDER ============ */
function NeedsDev({ onAction, status, canEdit }) {
  return (
    <div className="text-center py-16">
      <FlaskConical className="h-16 w-16 mx-auto mb-4 text-muted-foreground/30" />
      <h3 className="text-lg font-semibold mb-2">Desenvolvimento não iniciado</h3>
      <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">
        Para acessar formulação, testes, amostras, custos e documentos, inicie o desenvolvimento.
      </p>
      {status === "OPEN" && canEdit && (
        <Button onClick={onAction} className="gap-2">
          <ArrowRight className="h-4 w-4" />
          Iniciar Desenvolvimento
        </Button>
      )}
    </div>
  );
}

/* ============ OVERVIEW TAB ============ */
function OverviewTab({ req, dev, formulas, tests, samples, approval, costs, history, onRefresh, hasDev, clientInfo, canEdit, canApproveCommercial, canManageApproval, onCommercialApprove, onCommercialReject, formulaCostData, setActiveTab, documents, updates, pending, canViewCommercial, labResults }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({});
  const [showBriefingDetail, setShowBriefingDetail] = useState(false);

  const startEditing = () => {
    setForm({
      project_name: req.project_name || "",
      request_type: req.request_type || "Produto Novo",
      category: req.category || "",
      description: req.description || "",
      references: req.references || "",
      restrictions: req.restrictions || "",
      volume: req.volume || "",
      packaging: req.packaging || "",
      priority: req.priority || "Normal",
      deadline: req.deadline || "",
    });
    setEditing(true);
  };

  const saveChanges = async () => {
    setSaving(true);
    try {
      await api.put(`/pd/requests/${req.id}`, form);
      toast.success("Solicitação atualizada!");
      setEditing(false);
      onRefresh();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const [showApproval, setShowApproval] = useState(false);
  const [approvalForm, setApprovalForm] = useState({
    approved_by_client: approval?.approved_by_client || false,
    approved_by_internal: approval?.approved_by_internal || false,
    notes: approval?.notes || "",
  });
  const [savingApproval, setSavingApproval] = useState(false);
  const canEditInternalApproval = Boolean(canEdit);
  const canEditClientApproval = Boolean(canEdit || canApproveCommercial);
  const canUseCommercialDecision = Boolean(canApproveCommercial && req.status === "WAITING_APPROVAL");

  useEffect(() => {
    setApprovalForm({
      approved_by_client: approval?.approved_by_client || false,
      approved_by_internal: approval?.approved_by_internal || false,
      notes: approval?.notes || "",
    });
  }, [approval]);

  const saveApproval = async () => {
    if (!dev) return;
    setSavingApproval(true);
    try {
      const payload = canEdit
        ? approvalForm
        : {
            approved_by_client: approvalForm.approved_by_client,
            approved_by_internal: approval?.approved_by_internal || false,
            notes: approvalForm.notes || "",
          };
      await api.post(`/pd/developments/${dev.id}/approval`, payload);
      toast.success("Aprovação registrada!");
      setShowApproval(false);
      onRefresh();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao salvar aprovação");
    } finally {
      setSavingApproval(false);
    }
  };

  const STAGE_ORDER = ["OPEN", "IN_PROGRESS", "IN_TESTS", "WAITING_APPROVAL", "APPROVED", "COMPLETED"];
  const currentStageIndex = STAGE_ORDER.indexOf(req.status);
  const unlocked = (s) => currentStageIndex >= STAGE_ORDER.indexOf(s);

  // Locked section placeholder — greyed dashed card
  const LockedSection = ({ accentColor, Icon, title, unlockStage }) => (
    <div className="border border-dashed rounded-xl overflow-hidden opacity-50">
      <div className="flex items-center justify-between px-6 py-3.5 bg-muted/10">
        <div className="flex items-center gap-3">
          <span className={`w-1 h-4 ${accentColor} rounded-full opacity-40`} />
          {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground/50" />}
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/60">{title}</p>
        </div>
        <div className="flex items-center gap-1.5 text-[9px] text-muted-foreground/50">
          <Lock className="h-3 w-3" />
          {STATUS_CONFIG[unlockStage]?.label || unlockStage}
        </div>
      </div>
    </div>
  );

  // Consistent section header
  const SectionHead = ({ accentColor, Icon, title, action }) => (
    <div className="flex items-center justify-between px-6 py-4 border-b bg-muted/20">
      <div className="flex items-center gap-3">
        <span className={`w-1 h-5 ${accentColor} rounded-full`} />
        {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground" />}
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{title}</p>
      </div>
      {action}
    </div>
  );

  // Nav button to full tab
  const GoBtn = ({ tab, label = "Ver completo" }) => setActiveTab ? (
    <button onClick={() => setActiveTab(tab)} className="flex items-center gap-1 text-[10px] text-primary hover:underline font-medium shrink-0">
      {label} <ChevronRight className="h-3 w-3" />
    </button>
  ) : null;

  const testStats = {
    total: tests.length,
    approved: tests.filter(t => t.status === "APPROVED").length,
    failed: tests.filter(t => t.status === "FAILED").length,
    pending: tests.filter(t => t.status === "PENDING" || t.status === "RUNNING").length,
  };

  const latestFormula = formulas.length > 0 ? formulas[formulas.length - 1] : null;
  const pendingUpdates = (pending || []).filter(p => p.status === "pendente").length;
  const lastUpdate = (updates || []).slice(-1)[0];

  return (
    <div className="space-y-4 max-w-4xl mx-auto">

      {/* — Stage Progress Track — */}
      <div className="bg-card border rounded-xl px-6 py-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground mb-4">Progresso do Projeto</p>
        <div className="flex items-start">
          {STAGE_ORDER.map((s, i) => {
            const cfg = STATUS_CONFIG[s];
            const isDone = currentStageIndex > i;
            const isCurrent = req.status === s;
            const isLast = i === STAGE_ORDER.length - 1;
            return (
              <React.Fragment key={s}>
                <div className="flex flex-col items-center gap-1.5 flex-1 min-w-0">
                  <div className={`w-7 h-7 rounded-full border-2 flex items-center justify-center transition-all shrink-0 ${
                    isDone
                      ? "bg-green-500 border-green-500 text-white"
                      : isCurrent
                      ? "bg-primary border-primary text-primary-foreground ring-4 ring-primary/20"
                      : "bg-muted border-border text-muted-foreground"
                  }`}>
                    {isDone
                      ? <CheckCircle2 className="h-3.5 w-3.5" />
                      : <span className="text-[10px] font-bold">{i + 1}</span>
                    }
                  </div>
                  <span className={`text-[9px] font-medium text-center leading-tight px-0.5 ${
                    isCurrent ? "text-primary" : isDone ? "text-muted-foreground" : "text-muted-foreground/50"
                  }`}>
                    {cfg.label}
                  </span>
                </div>
                {!isLast && <div className={`h-px flex-[2] mt-3.5 shrink-0 ${isDone ? "bg-green-400" : "bg-border"}`} />}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {/* — KPI Strip — */}
      {hasDev && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Fórmulas", value: formulas.length, Icon: Beaker, color: "text-violet-500", accent: "bg-violet-500/10 border-violet-200 dark:border-violet-800" },
            { label: "Testes", value: `${testStats.approved}/${testStats.total}`, sub: testStats.failed > 0 ? `${testStats.failed} falha(s)` : undefined, Icon: FlaskConical, color: "text-blue-500", accent: "bg-blue-500/10 border-blue-200 dark:border-blue-800" },
            { label: "Amostras", value: samples.length, Icon: Package, color: "text-amber-500", accent: "bg-amber-500/10 border-amber-200 dark:border-amber-800" },
            { label: "Custo Unit.", value: formulaCostData ? `R$ ${formulaCostData.custo_unitario.toFixed(2)}` : "—", Icon: DollarSign, color: "text-emerald-600", accent: "bg-emerald-500/10 border-emerald-200 dark:border-emerald-800" },
          ].map(({ label, value, sub, Icon, color, accent }) => (
            <div key={label} className={`rounded-xl border px-4 py-3 ${accent} flex items-center gap-3`}>
              <Icon className={`h-5 w-5 shrink-0 ${color}`} />
              <div className="min-w-0">
                <p className="font-mono text-lg font-bold leading-none">{value}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">{label}</p>
                {sub && <p className="text-[9px] text-red-500 mt-0.5">{sub}</p>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* — Briefing CRM — */}
      {clientInfo && (
        <>
          <div className="border rounded-xl overflow-hidden">
            <button
              className="w-full flex items-center justify-between px-6 py-4 hover:bg-muted/40 transition-colors group text-left"
              onClick={() => setShowBriefingDetail(true)}
              data-testid="briefing-card-clickable"
            >
              <div className="flex items-center gap-3">
                <span className="w-1 h-5 bg-blue-500 rounded-full shrink-0" />
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Briefing do Projeto · CRM</p>
                  <p className="text-sm font-medium mt-0.5">{clientInfo.nome_projeto || clientInfo.nome_cliente || "Projeto"}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 text-muted-foreground group-hover:text-blue-500 transition-colors shrink-0">
                <Badge variant="outline" className="text-[9px]">Dados do Pipeline</Badge>
                <Eye className="h-4 w-4" />
              </div>
            </button>
            <div className="border-t px-6 py-4 grid grid-cols-2 sm:grid-cols-3 gap-x-8 gap-y-3">
              {[
                ["Produto", clientInfo.produto],
                ["Cliente", clientInfo.nome_cliente],
                ["Orçamento", clientInfo.orcamento_projeto],
                ["Textura", clientInfo.textura_esperada],
                ["Aplicação", clientInfo.aplicacao],
                ["pH Alvo", clientInfo.ph],
              ].filter(([, v]) => v).map(([label, value]) => (
                <div key={label}>
                  <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">{label}</p>
                  <p className="text-sm font-medium">{value}</p>
                </div>
              ))}
            </div>
            {clientInfo.objetivo_projeto && (
              <div className="border-t px-6 py-3">
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Objetivo</p>
                <p className="text-sm text-muted-foreground line-clamp-2">{clientInfo.objetivo_projeto}</p>
              </div>
            )}
            <button
              className="w-full border-t px-6 py-2.5 bg-muted/20 hover:bg-muted/50 transition-colors flex items-center justify-center gap-1.5 text-[10px] text-muted-foreground hover:text-blue-500"
              onClick={() => setShowBriefingDetail(true)}
            >
              <Eye className="h-3 w-3" /> Clique para ver todas as informações do briefing
            </button>
          </div>

          <Dialog open={showBriefingDetail} onOpenChange={setShowBriefingDetail}>
            <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="briefing-detail-dialog">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                  Briefing do Projeto (CRM)
                  <Badge variant="outline" className="text-[10px] ml-2">Dados do Pipeline</Badge>
                </DialogTitle>
                <DialogDescription>
                  Todas as informações do projeto vindas do CRM / Pipeline
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-5 text-sm py-2">
                <section>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 flex items-center gap-2">
                    <span className="w-1 h-4 bg-blue-500 rounded" /> Identificação
                  </h4>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-3 pl-3">
                    <InfoRow label="1. Produto" value={clientInfo.produto} />
                    <InfoRow label="2. Cliente" value={clientInfo.nome_cliente} />
                    <InfoRow label="3. Nome do Projeto" value={clientInfo.nome_projeto} />
                    <InfoRow label="9. Orçamento" value={clientInfo.orcamento_projeto} />
                  </div>
                </section>
                <section>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 flex items-center gap-2">
                    <span className="w-1 h-4 bg-purple-500 rounded" /> Especificações Técnicas
                  </h4>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-3 pl-3">
                    <InfoRow label="10. Textura Esperada" value={clientInfo.textura_esperada} />
                    <InfoRow label="11. Aplicação" value={clientInfo.aplicacao} />
                    <InfoRow label="12. Sensorial" value={clientInfo.sensorial} />
                    <InfoRow label="13. pH" value={clientInfo.ph} />
                  </div>
                </section>
                {(clientInfo.objetivo_projeto || clientInfo.aplicacoes_desenvolver || clientInfo.ativos_claims) && (
                  <section>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 flex items-center gap-2">
                      <span className="w-1 h-4 bg-green-500 rounded" /> Objetivos & Detalhes do Projeto
                    </h4>
                    <div className="space-y-3 pl-3">
                      {clientInfo.objetivo_projeto && (
                        <div>
                          <span className="text-muted-foreground text-xs font-medium block mb-1">4. Objetivo do Projeto</span>
                          <p className="whitespace-pre-wrap bg-muted/40 p-3 rounded-md">{clientInfo.objetivo_projeto}</p>
                        </div>
                      )}
                      {clientInfo.aplicacoes_desenvolver && (
                        <div>
                          <span className="text-muted-foreground text-xs font-medium block mb-1">5. Aplicações a Desenvolver</span>
                          <p className="whitespace-pre-wrap bg-muted/40 p-3 rounded-md">{clientInfo.aplicacoes_desenvolver}</p>
                        </div>
                      )}
                      {clientInfo.ativos_claims && (
                        <div>
                          <span className="text-muted-foreground text-xs font-medium block mb-1">6. Ativos para Claims</span>
                          <p className="whitespace-pre-wrap bg-muted/40 p-3 rounded-md">{clientInfo.ativos_claims}</p>
                        </div>
                      )}
                    </div>
                  </section>
                )}
                {(clientInfo.referencias || clientInfo.referencias_fotos_url) && (
                  <section>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 flex items-center gap-2">
                      <span className="w-1 h-4 bg-amber-500 rounded" /> Referências
                    </h4>
                    <div className="space-y-3 pl-3">
                      {clientInfo.referencias && (
                        <div>
                          <span className="text-muted-foreground text-xs font-medium block mb-1">7. Referências</span>
                          <p className="whitespace-pre-wrap bg-muted/40 p-3 rounded-md">{clientInfo.referencias}</p>
                        </div>
                      )}
                      {clientInfo.referencias_fotos_url && (
                        <div>
                          <span className="text-muted-foreground text-xs font-medium block mb-1">8. Referências Fotos</span>
                          <a href={clientInfo.referencias_fotos_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline text-sm break-all bg-muted/40 p-3 rounded-md block">
                            {clientInfo.referencias_fotos_url}
                          </a>
                        </div>
                      )}
                    </div>
                  </section>
                )}
                {clientInfo.outras_observacoes && (
                  <section>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 flex items-center gap-2">
                      <span className="w-1 h-4 bg-rose-500 rounded" /> Outras Observações
                    </h4>
                    <div className="pl-3">
                      <span className="text-muted-foreground text-xs font-medium block mb-1">14. Outras Observações</span>
                      <p className="whitespace-pre-wrap bg-muted/40 p-3 rounded-md">{clientInfo.outras_observacoes}</p>
                    </div>
                  </section>
                )}
                {(clientInfo.feedback_cliente || clientInfo.direcoes_retrabalho || clientInfo.resultado_cliente) && (
                  <section>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 flex items-center gap-2">
                      <span className="w-1 h-4 bg-amber-500 rounded" /> Retorno Comercial / Cliente
                    </h4>
                    <div className="space-y-3 pl-3">
                      {clientInfo.resultado_cliente && (
                        <div>
                          <span className="text-muted-foreground text-xs font-medium block mb-1">Resultado</span>
                          <p className="whitespace-pre-wrap bg-muted/40 p-3 rounded-md">{clientInfo.resultado_cliente}</p>
                        </div>
                      )}
                      {clientInfo.feedback_cliente && (
                        <div>
                          <span className="text-muted-foreground text-xs font-medium block mb-1">Feedback do cliente</span>
                          <p className="whitespace-pre-wrap bg-muted/40 p-3 rounded-md">{clientInfo.feedback_cliente}</p>
                        </div>
                      )}
                      {clientInfo.direcoes_retrabalho && (
                        <div>
                          <span className="text-muted-foreground text-xs font-medium block mb-1">Orientações para retrabalho</span>
                          <p className="whitespace-pre-wrap bg-muted/40 p-3 rounded-md">{clientInfo.direcoes_retrabalho}</p>
                        </div>
                      )}
                    </div>
                  </section>
                )}
                <section className="pt-3 border-t">
                  <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>
                      {req.created_by_name && <>Criado por <strong>{req.created_by_name}</strong></>}
                      {req.created_at && <> em {new Date(req.created_at).toLocaleDateString("pt-BR")}</>}
                    </span>
                    {clientInfo.nome_cliente && (
                      <Badge variant="secondary" className="text-[10px]">Cliente: {clientInfo.nome_cliente}</Badge>
                    )}
                  </div>
                </section>
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={() => setShowBriefingDetail(false)} data-testid="close-briefing-detail-btn">
                  Fechar
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}

      {/* — Detalhes da Solicitação — */}
      <div className="border rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b bg-muted/20">
          <div className="flex items-center gap-3">
            <span className="w-1 h-5 bg-primary rounded-full" />
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Detalhes da Solicitação</p>
          </div>
          {!editing ? (
            canEdit && (
              <Button size="sm" variant="ghost" onClick={startEditing} className="gap-1.5 text-xs h-7">
                <Pencil className="h-3 w-3" /> Editar
              </Button>
            )
          ) : (
            <div className="flex gap-1.5">
              <Button size="sm" variant="default" onClick={saveChanges} disabled={saving} className="gap-1 text-xs h-7">
                <Save className="h-3 w-3" />{saving ? "Salvando..." : "Salvar"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)} className="h-7">
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </div>
        <div className="px-6 py-5">
          {!editing ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-8 gap-y-4">
                {[
                  ["Tipo", req.request_type],
                  ["Categoria", req.category],
                  ["Prioridade", req.priority],
                  ["Prazo", req.deadline ? new Date(req.deadline).toLocaleDateString("pt-BR") : null],
                  ["Volume", req.volume],
                  ["Embalagem", req.packaging],
                ].map(([label, value]) => (
                  <div key={label}>
                    <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">{label}</p>
                    <p className="text-sm font-medium">{value || "—"}</p>
                  </div>
                ))}
              </div>
              {(req.status === "APPROVED" || req.status === "COMPLETED") && (
                <div className="border-t pt-3">
                  <SkuField reqId={req.id} currentSku={req.sku} canEdit={canEdit} onRefresh={onRefresh} />
                </div>
              )}
              {req.description && (
                <div className="border-t pt-3">
                  <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Descrição / Briefing</p>
                  <p className="text-sm whitespace-pre-wrap text-muted-foreground">{req.description}</p>
                </div>
              )}
              {req.references && (
                <div className="border-t pt-3">
                  <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Referências</p>
                  <p className="text-sm whitespace-pre-wrap text-muted-foreground">{req.references}</p>
                </div>
              )}
              <div className="border-t pt-3 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <Clock className="h-3 w-3" />
                Criado por <span className="font-medium">{req.created_by_name}</span> em {new Date(req.created_at).toLocaleDateString("pt-BR")}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <Label>Nome do Projeto</Label>
                <Input value={form.project_name} onChange={e => setForm(p => ({ ...p, project_name: e.target.value }))} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Tipo</Label>
                  <Select value={form.request_type} onValueChange={v => setForm(p => ({ ...p, request_type: v }))}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{REQUEST_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Categoria</Label>
                  <Select value={form.category || "placeholder"} onValueChange={v => setForm(p => ({ ...p, category: v === "placeholder" ? "" : v }))}>
                    <SelectTrigger><SelectValue placeholder="Selecionar..." /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="placeholder" disabled>Selecionar...</SelectItem>
                      {CATEGORIES.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Prioridade</Label>
                  <Select value={form.priority} onValueChange={v => setForm(p => ({ ...p, priority: v }))}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{PRIORITIES.map(pr => <SelectItem key={pr} value={pr}>{pr}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Prazo</Label>
                  <Input type="date" value={form.deadline} onChange={e => setForm(p => ({ ...p, deadline: e.target.value }))} />
                </div>
              </div>
              <div>
                <Label>Descrição</Label>
                <Textarea value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} rows={3} />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── MANIPULAÇÃO ─────────────────────────────────────── */}
      {unlocked("IN_PROGRESS") && hasDev ? (
        <div className="border rounded-xl overflow-hidden">
          <SectionHead accentColor="bg-violet-500" Icon={Beaker} title="Manipulação · Fórmulas" action={<GoBtn tab="formula" />} />
          <div className="px-6 py-4">
            {formulas.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma fórmula criada ainda.</p>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-8 gap-y-3">
                  <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Fórmulas</p><p className="text-sm font-semibold">{formulas.length}</p></div>
                  <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Versão Ativa</p><p className="text-sm font-semibold">{latestFormula?.version ? `v${latestFormula.version}` : "—"}</p></div>
                  <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Ingredientes</p><p className="text-sm font-semibold">{latestFormula?.items?.length ?? "—"}</p></div>
                  <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Volume</p><p className="text-sm font-semibold">{latestFormula ? `${latestFormula.volume} ${latestFormula.volume_unit}` : "—"}</p></div>
                </div>
                {latestFormula && (
                  <p className="text-xs text-muted-foreground border-t pt-2">Última: <span className="font-medium text-foreground">{latestFormula.name}</span></p>
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <LockedSection accentColor="bg-violet-500" Icon={Beaker} title="Manipulação · Fórmulas" unlockStage="IN_PROGRESS" />
      )}

      {/* ── TESTES LABORATORIAIS ─────────────────────────── */}
      {unlocked("IN_PROGRESS") && hasDev ? (
        <div className="border rounded-xl overflow-hidden">
          <SectionHead accentColor="bg-blue-500" Icon={FlaskConical} title="Testes Laboratoriais" action={<GoBtn tab="tests" />} />
          <div className="px-6 py-4">
            {tests.length === 0 && !labResults?.updated_at ? (
              <p className="text-sm text-muted-foreground">Nenhum teste registrado ainda.</p>
            ) : (
              <div className="space-y-3">
                {tests.length > 0 && (
                  <div className="flex items-center gap-4 flex-wrap">
                    {[
                      { label: "Total", value: testStats.total, color: "text-foreground" },
                      { label: "Aprovados", value: testStats.approved, color: "text-green-600" },
                      { label: "Falhas", value: testStats.failed, color: "text-red-500" },
                      { label: "Pendentes", value: testStats.pending, color: "text-amber-500" },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="flex flex-col items-center gap-0.5 min-w-[48px]">
                        <span className={`text-xl font-bold font-mono ${color}`}>{value}</span>
                        <span className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</span>
                      </div>
                    ))}
                    <div className="ml-auto">
                      {testStats.failed > 0 && <Badge className="bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 text-[10px]">{testStats.failed} falha(s)</Badge>}
                      {testStats.failed === 0 && testStats.total > 0 && testStats.pending === 0 && <Badge className="bg-green-100 text-green-700 text-[10px]">Todos aprovados</Badge>}
                    </div>
                  </div>
                )}
                {labResults?.updated_at && (
                  <div className="flex flex-wrap gap-2">
                    {[
                      { label: "pH", val: labResults.ph?.valor },
                      { label: "Viscosidade", val: labResults.viscosidade?.valor ? `${labResults.viscosidade.valor} ${labResults.viscosidade.unidade || ""}`.trim() : null },
                      { label: "Estabilidade", val: labResults.estabilidade?.resultado },
                      { label: "Sensorial", val: labResults.sensorial?.aparencia },
                    ].filter(f => f.val).map(f => (
                      <span key={f.label} className="text-[11px] rounded-md border px-2 py-0.5 bg-muted/40">
                        <span className="text-muted-foreground">{f.label}: </span>
                        <span className="font-medium">{f.val}</span>
                      </span>
                    ))}
                    <Badge className="bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300 text-[10px]">Registros preenchidos</Badge>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <LockedSection accentColor="bg-blue-500" Icon={FlaskConical} title="Testes Laboratoriais" unlockStage="IN_PROGRESS" />
      )}

      {/* ── AMOSTRAS ────────────────────────────────────────── */}
      {unlocked("IN_PROGRESS") && hasDev ? (
        <div className="border rounded-xl overflow-hidden">
          <SectionHead accentColor="bg-amber-500" Icon={Package} title="Amostras Físicas" action={<GoBtn tab="samples" />} />
          <div className="px-6 py-4">
            {samples.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma amostra gerada ainda.</p>
            ) : (
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-x-8 gap-y-2">
                  <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Total de Amostras</p><p className="text-sm font-semibold">{samples.length}</p></div>
                  <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Última Amostra</p><p className="text-sm font-semibold truncate">{samples[samples.length - 1]?.name || "—"}</p></div>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <LockedSection accentColor="bg-amber-500" Icon={Package} title="Amostras Físicas" unlockStage="IN_PROGRESS" />
      )}

      {/* ── FICHA TÉCNICA ────────────────────────────────── */}
      {unlocked("IN_PROGRESS") && hasDev ? (
        <div className="border rounded-xl overflow-hidden">
          <SectionHead accentColor="bg-indigo-500" Icon={ClipboardList} title="Ficha Técnica" action={<GoBtn tab="ficha_tecnica" />} />
          <div className="px-6 py-4 flex items-center gap-3 flex-wrap">
            <p className="text-sm text-muted-foreground flex-1">Documento técnico completo da fórmula.</p>
            <Button size="sm" variant="outline" className="gap-1.5 text-xs h-7" onClick={() => setActiveTab && setActiveTab("ficha_tecnica")}>
              <ClipboardList className="h-3 w-3" /> Abrir Ficha
            </Button>
          </div>
        </div>
      ) : (
        <LockedSection accentColor="bg-indigo-500" Icon={ClipboardList} title="Ficha Técnica" unlockStage="IN_PROGRESS" />
      )}

      {/* ── CUSTOS P&D ───────────────────────────────────── */}
      {unlocked("IN_PROGRESS") && hasDev ? (
        <div className="border rounded-xl overflow-hidden">
          <SectionHead accentColor="bg-emerald-500" Icon={DollarSign} title="Custos P&D" action={<GoBtn tab="costs" />} />
          <div className="px-6 py-4">
            {formulaCostData ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-8 gap-y-3">
                <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Custo Unitário</p><p className="text-sm font-semibold font-mono">R$ {formulaCostData.custo_unitario?.toFixed(2) ?? "—"}</p></div>
                <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Custo / kg</p><p className="text-sm font-semibold font-mono">R$ {formulaCostData.total_cost_per_kg?.toFixed(4) ?? "—"}</p></div>
                <div><p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-0.5">Versões</p><p className="text-sm font-semibold">{(costs || []).length}</p></div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Nenhuma versão de custo calculada ainda.</p>
            )}
          </div>
        </div>
      ) : (
        <LockedSection accentColor="bg-emerald-500" Icon={DollarSign} title="Custos P&D" unlockStage="IN_PROGRESS" />
      )}

      {/* ── COMERCIAL ────────────────────────────────────── */}
      {canViewCommercial && unlocked("WAITING_APPROVAL") ? (
        <div className="border rounded-xl overflow-hidden">
          <SectionHead accentColor="bg-rose-500" Icon={Building2} title="Comercial" action={<GoBtn tab="comercial" />} />
          <div className="px-6 py-4">
            <p className="text-sm text-muted-foreground">Versões de custo com margens e preços comerciais.</p>
          </div>
        </div>
      ) : canViewCommercial ? (
        <LockedSection accentColor="bg-rose-500" Icon={Building2} title="Comercial" unlockStage="WAITING_APPROVAL" />
      ) : null}

      {/* ── APROVAÇÃO ────────────────────────────────────── */}
      {hasDev && (
        <div className={`border rounded-xl overflow-hidden ${
          approval?.approved_by_client && approval?.approved_by_internal
            ? "border-green-300 dark:border-green-800"
            : approval ? "border-orange-300 dark:border-orange-800" : ""
        }`}>
          <div className="flex items-center justify-between px-6 py-4 border-b bg-muted/20">
            <div className="flex items-center gap-3">
              <span className="w-1 h-5 bg-green-500 rounded-full" />
              <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Aprovação</p>
            </div>
            <Button size="sm" variant={showApproval ? "secondary" : "outline"} onClick={() => setShowApproval(!showApproval)} className="gap-1.5 text-xs h-7" disabled={!canManageApproval}>
              {showApproval ? <X className="h-3 w-3" /> : <Pencil className="h-3 w-3" />}
              {showApproval ? "Fechar" : (approval ? "Editar" : "Registrar")}
            </Button>
          </div>
          <div className="px-6 py-4">
            {!showApproval ? (
              approval ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-3 flex-wrap">
                    {approval.approved_by_client ? (
                      <Badge className="bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300 gap-1"><CheckCircle2 className="h-3 w-3" />Cliente Aprovou</Badge>
                    ) : (
                      <Badge className="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 gap-1"><Clock className="h-3 w-3" />Cliente Pendente</Badge>
                    )}
                    {approval.approved_by_internal ? (
                      <Badge className="bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300 gap-1"><CheckCircle2 className="h-3 w-3" />Aprovação Interna</Badge>
                    ) : (
                      <Badge className="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 gap-1"><Clock className="h-3 w-3" />Interno Pendente</Badge>
                    )}
                    {approval.approved_by_comercial && (
                      <Badge className="bg-rose-100 text-rose-700 dark:bg-rose-900 dark:text-rose-300 gap-1"><Building2 className="h-3 w-3" />Comercial Aprovou</Badge>
                    )}
                  </div>
                  {approval.notes && <p className="text-xs text-muted-foreground bg-muted/50 p-2 rounded mt-2">{approval.notes}</p>}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Nenhuma aprovação registrada.</p>
              )
            ) : (
              <div className="space-y-4">
                <div className="flex items-center gap-6">
                  <div className="flex items-center gap-2">
                    <Switch checked={approvalForm.approved_by_client} disabled={!canEditClientApproval} onCheckedChange={v => setApprovalForm(p => ({ ...p, approved_by_client: v }))} />
                    <Label>Aprovação do Cliente</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch checked={approvalForm.approved_by_internal} disabled={!canEditInternalApproval} onCheckedChange={v => setApprovalForm(p => ({ ...p, approved_by_internal: v }))} />
                    <Label>Aprovação Interna</Label>
                  </div>
                </div>
                {!canEditInternalApproval && canEditClientApproval && (
                  <p className="text-xs text-muted-foreground">
                    O Comercial pode registrar a aprovação do cliente e despachar a aprovação final. A aprovação interna permanece sob responsabilidade do P&D.
                  </p>
                )}
                <div>
                  <Label>Observações</Label>
                  <Textarea value={approvalForm.notes} onChange={e => setApprovalForm(p => ({ ...p, notes: e.target.value }))} rows={2} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={saveApproval} disabled={savingApproval || !canManageApproval} className="gap-1.5">
                    <Save className="h-3.5 w-3.5" />
                    {savingApproval ? "Salvando..." : "Salvar Aprovação"}
                  </Button>
                  {canUseCommercialDecision && (
                    <>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={onCommercialReject}
                        disabled={savingApproval}
                        className="gap-1.5"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        Reprovar Comercialmente
                      </Button>
                      <Button
                        size="sm"
                        onClick={onCommercialApprove}
                        disabled={savingApproval}
                        className="gap-1.5 bg-green-600 hover:bg-green-700 text-white"
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Aprovar Comercialmente
                      </Button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── DOCUMENTOS ───────────────────────────────────── */}
      {unlocked("IN_PROGRESS") && hasDev ? (
        <div className="border rounded-xl overflow-hidden">
          <SectionHead accentColor="bg-orange-500" Icon={FileText} title="Documentos" action={<GoBtn tab="documents" />} />
          <div className="px-6 py-4">
            {(documents || []).length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhum documento anexado ainda.</p>
            ) : (
              <div className="flex items-center gap-3">
                <span className="text-2xl font-bold font-mono">{documents.length}</span>
                <span className="text-sm text-muted-foreground">documento(s) anexado(s)</span>
              </div>
            )}
          </div>
        </div>
      ) : (
        <LockedSection accentColor="bg-orange-500" Icon={FileText} title="Documentos" unlockStage="IN_PROGRESS" />
      )}

      {/* ── DOCUMENTOS VIVOS ─────────────────────────────── */}
      <div className="border rounded-xl overflow-hidden">
        <SectionHead accentColor="bg-teal-500" Icon={ShieldCheck} title="Documentos Vivos" action={<GoBtn tab="live_docs" />} />
        <div className="px-6 py-4">
          <p className="text-sm text-muted-foreground">Documentos regulatórios e de conformidade vinculados ao projeto.</p>
        </div>
      </div>

      {/* ── ATUALIZAÇÕES ─────────────────────────────────── */}
      <div className="border rounded-xl overflow-hidden">
        <SectionHead accentColor="bg-amber-500" Icon={Bell} title="Atualizações" action={<GoBtn tab="updates" />} />
        <div className="px-6 py-4">
          {pendingUpdates > 0 && (
            <Badge className="bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 gap-1 mb-2">
              <Hourglass className="h-3 w-3" /> {pendingUpdates} pendência(s)
            </Badge>
          )}
          {lastUpdate ? (
            <p className="text-xs text-muted-foreground line-clamp-2">{lastUpdate.content || lastUpdate.message || "Sem conteúdo"}</p>
          ) : (
            <p className="text-sm text-muted-foreground">Nenhuma atualização registrada.</p>
          )}
        </div>
      </div>

      {/* ── HISTÓRICO DE STATUS ──────────────────────────── */}
      <div className="border rounded-xl overflow-hidden">
        <div className="flex items-center gap-3 px-6 py-4 border-b bg-muted/20">
          <span className="w-1 h-5 bg-slate-400 rounded-full" />
          <History className="h-3.5 w-3.5 text-muted-foreground" />
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Histórico de Status</p>
        </div>
        <div className="px-6 py-4">
          <div className="space-y-0">
            {history.map((h, i) => (
              <div key={h.id} className="flex gap-3 text-sm">
                <div className="flex flex-col items-center">
                  <div className={`w-2.5 h-2.5 rounded-full mt-1.5 shrink-0 ${STATUS_CONFIG[h.to_status]?.dotColor || "bg-gray-400"}`} />
                  {i < history.length - 1 && <div className="w-px flex-1 bg-border" style={{ minHeight: 20 }} />}
                </div>
                <div className="pb-4">
                  <div className="font-medium text-xs">{STATUS_CONFIG[h.to_status]?.label || h.to_status}</div>
                  <div className="text-xs text-muted-foreground">{h.comment}</div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    {h.changed_by_name} • {new Date(h.created_at).toLocaleString("pt-BR")}
                  </div>
                </div>
              </div>
            ))}
            {history.length === 0 && <p className="text-xs text-muted-foreground">Sem histórico</p>}
          </div>
        </div>
      </div>

    </div>
  );
}

/* Helpers */
function InfoRow({ label, value }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-muted-foreground text-xs shrink-0">{label}:</span>
      <span className="text-sm font-medium">{value || "—"}</span>
    </div>
  );
}

function MiniCard({ icon: Icon, label, value, color, extra, extraColor }) {
  return (
    <div className="rounded-lg border p-3 text-center">
      <Icon className={`h-5 w-5 mx-auto mb-1 ${color}`} />
      <div className="text-base font-bold">{value}</div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      {extra && <div className={`text-[10px] ${extraColor || "text-muted-foreground"}`}>{extra}</div>}
    </div>
  );
}

/* ============ FORMULA TAB (Manipulação) ============ */
// B13: busca no banco de fórmulas (GET /pd/formulas/bank já traz a composição completa
// quando o perfil pode ver custos — reaproveitado aqui tanto pra busca quanto preview,
// sem precisar de um endpoint novo só pra isso) e copia como rascunho no desenvolvimento atual.
function ImportFormulaDialog({ open, onOpenChange, devId, onImported }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    if (!open) { setQuery(""); setResults([]); setSelected(null); return; }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const { data } = await api.get("/pd/formulas/bank", { params: query.trim() ? { q: query.trim() } : {} });
        setResults((Array.isArray(data) ? data : []).filter(f => f.development_id !== devId).slice(0, 30));
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [open, query, devId]);

  const handleImport = async () => {
    if (!selected) return;
    setImporting(true);
    try {
      const { data } = await api.post(`/pd/formulas/${selected.id}/import-into/${devId}`);
      toast.success(`Fórmula "${data.name}" importada como rascunho (v${data.version}).`);
      onOpenChange(false);
      onImported?.();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao importar fórmula");
    } finally {
      setImporting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Importar Fórmula</DialogTitle>
          <p className="text-xs text-muted-foreground">
            Busque uma fórmula de outra requisição e importe a composição como rascunho editável aqui —
            a fórmula de origem não é alterada.
          </p>
        </DialogHeader>
        <div className="space-y-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input className="pl-8" placeholder="Buscar por produto, cliente, ingrediente..." value={query} onChange={(e) => { setQuery(e.target.value); setSelected(null); }} />
          </div>

          {!selected && (
            <div className="border rounded-md max-h-64 overflow-y-auto divide-y">
              {loading && <div className="p-3 text-xs text-muted-foreground">Buscando...</div>}
              {!loading && results.length === 0 && (
                <div className="p-3 text-xs text-muted-foreground">Nenhuma fórmula encontrada.</div>
              )}
              {results.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  disabled={f.restricted_view}
                  onClick={() => setSelected(f)}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-between gap-2"
                  title={f.restricted_view ? "Seu perfil não pode ver a composição desta fórmula" : ""}
                >
                  <span className="min-w-0">
                    <span className="font-medium truncate block">{f.name} <span className="text-muted-foreground font-normal">v{f.version}</span></span>
                    <span className="text-xs text-muted-foreground truncate block">{f.project_name} — {f.origin_label}</span>
                  </span>
                  <span className="text-[10px] text-muted-foreground shrink-0">{f.item_count} item(ns)</span>
                </button>
              ))}
            </div>
          )}

          {selected && (
            <div className="border rounded-md p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold">{selected.name} <span className="text-muted-foreground font-normal">v{selected.version}</span></p>
                  <p className="text-xs text-muted-foreground">{selected.project_name} — {selected.origin_label}</p>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>Trocar</Button>
              </div>
              <div className="max-h-56 overflow-y-auto border rounded">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-muted/50 text-left">
                      <th className="p-1.5 font-medium">Ingrediente</th>
                      <th className="p-1.5 font-medium text-right">%</th>
                      <th className="p-1.5 font-medium">Fase</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(selected.items || []).map((it, idx) => (
                      <tr key={idx} className="border-t">
                        <td className="p-1.5">{it.ingredient_name}</td>
                        <td className="p-1.5 text-right font-mono">{(it.percentage || 0).toFixed(2)}</td>
                        <td className="p-1.5">{it.phase || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button onClick={handleImport} disabled={!selected || importing} className="gap-1.5">
            <Copy className="h-3.5 w-3.5" /> Importar como rascunho
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FormulaTab({ devId, formulas, onRefresh, canEdit, clientInfo, req }) {
  const { ingredientOptions, getSuppliersForIngredient } = usePdMaterialLibrary();
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [formulaName, setFormulaName] = useState("");
  const [formulaNotes, setFormulaNotes] = useState("");
  const [formulaVolume, setFormulaVolume] = useState("");
  const [formulaVolumeUnit, setFormulaVolumeUnit] = useState("mL");
  const [formulaIndicePerdas, setFormulaIndicePerdas] = useState("0");
  const [formulaCotacao, setFormulaCotacao] = useState("6.00");
  const [saving, setSaving] = useState(false);
  const [expandedFormula, setExpandedFormula] = useState(formulas[0]?.id || null);
  const [newItem, setNewItem] = useState({ ingredient_name: "", percentage: "", price_per_kg: "", price_usd: "", price_currency: "BRL", fornecedor: "", phase: "", function: "", catalog_id: "" });
  const [editingConfig, setEditingConfig] = useState(null);
  const [configForm, setConfigForm] = useState({});
  const [editingItemId, setEditingItemId] = useState(null);
  const [editItemForm, setEditItemForm] = useState({ ingredient_name: "", fornecedor: "", percentage: "", price_per_kg: "", price_usd: "", price_currency: "BRL" });
  const [pendingCatalogItem, setPendingCatalogItem] = useState(null);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [showNewVersion, setShowNewVersion] = useState(null); // formula to create new version from
  const [newVersionJustification, setNewVersionJustification] = useState("");
  const [creatingVersion, setCreatingVersion] = useState(false);

  const filteredCatalog = newItem.ingredient_name
    ? ingredientOptions.filter((item) =>
        item.nome.toLowerCase().includes(newItem.ingredient_name.toLowerCase()) ||
        (item.inci && item.inci.toLowerCase().includes(newItem.ingredient_name.toLowerCase())) ||
        (item.codigo_interno && item.codigo_interno.toLowerCase().includes(newItem.ingredient_name.toLowerCase())),
      )
    : ingredientOptions;

  const newItemSuppliers = useMemo(
    () => getSuppliersForIngredient(newItem.ingredient_name),
    [getSuppliersForIngredient, newItem.ingredient_name],
  );
  const editItemSuppliers = useMemo(
    () => getSuppliersForIngredient(editItemForm.ingredient_name),
    [editItemForm.ingredient_name, getSuppliersForIngredient],
  );

  const supplierRankColor = (rank) => {
    if (rank === 0) return "text-green-700 bg-green-50 border-green-200 hover:bg-green-100";
    if (rank === 1) return "text-yellow-700 bg-yellow-50 border-yellow-200 hover:bg-yellow-100";
    if (rank === 2) return "text-orange-600 bg-orange-50 border-orange-200 hover:bg-orange-100";
    return "text-red-600 bg-red-50 border-red-200 hover:bg-red-100";
  };

  const pickFromCatalog = (cat) => {
    const fornecedores = (cat.fornecedores || [])
      .slice()
      .sort((a, b) => (a.preco_rs_kg ?? Number.MAX_SAFE_INTEGER) - (b.preco_rs_kg ?? Number.MAX_SAFE_INTEGER));
    if (fornecedores.length > 0) {
      setNewItem(p => ({
        ...p,
        ingredient_name: cat.nome,
        catalog_id: cat.catalog_id || "",
        price_per_kg: fornecedores[0]?.preco_rs_kg != null ? String(fornecedores[0].preco_rs_kg) : "",
        price_currency: fornecedores[0]?.moeda || "BRL",
        fornecedor: "",
      }));
      setPendingCatalogItem({ ...cat, fornecedores });
    } else {
      setNewItem({
        ingredient_name: cat.nome,
        percentage: newItem.percentage,
        price_per_kg: cat.preco_rs_kg != null ? String(cat.preco_rs_kg) : "",
        price_currency: "BRL",
        fornecedor: cat.fornecedor || "",
        phase: newItem.phase,
        function: newItem.function,
        catalog_id: cat.catalog_id || "",
      });
      setPendingCatalogItem(null);
    }
    setShowSuggestions(false);
  };

  const handleSupplierInput = (value, formSetter, suppliers) => {
    const matched = findSupplierByName(suppliers, value);
    formSetter((prev) => ({
      ...prev,
      fornecedor: value,
      ...(matched && matched.preco_rs_kg !== null
        ? {
            price_per_kg: String(matched.preco_rs_kg),
            price_currency: matched.moeda || prev.price_currency || "BRL",
          }
        : {}),
    }));
  };

  const createNewVersion = async () => {
    if (!newVersionJustification.trim() || newVersionJustification.trim().length < 10) {
      return toast.error("Justificativa deve ter no mínimo 10 caracteres");
    }
    setCreatingVersion(true);
    try {
      await api.post(`/pd/formulas/${showNewVersion.id}/new-version`, { justification: newVersionJustification });
      toast.success(`Nova versão v${(showNewVersion.version || 1) + 1} criada!`);
      setShowNewVersion(null);
      setNewVersionJustification("");
      onRefresh();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao criar nova versão");
    } finally { setCreatingVersion(false); }
  };

  const createFormula = async () => {
    setSaving(true);
    try {
      await api.post(`/pd/developments/${devId}/formulas`, {
        name: formulaName,
        notes: formulaNotes,
        volume: parseFloat(formulaVolume) || 0,
        volume_unit: formulaVolumeUnit,
        indice_perdas: parseFloat(formulaIndicePerdas) || 0,
        cotacao_usd: parseFloat(formulaCotacao) || 6.00,
      });
      toast.success("Fórmula criada!");
      setFormulaName(""); setFormulaNotes(""); setFormulaVolume(""); setShowCreate(false);
      onRefresh();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro");
    } finally { setSaving(false); }
  };

  const addItem = async (formulaId) => {
    if (!newItem.ingredient_name || !newItem.percentage) return toast.error("Preencha ingrediente e %");
    try {
      const formula = formulas.find(f => f.id === formulaId);
      const cotacao = formula?.cotacao_usd || 6.00;
      const rawPrice = parseFloat(newItem.price_per_kg) || 0;
      const priceInBRL = newItem.price_currency === "USD" ? rawPrice * cotacao : rawPrice;
      await api.post(`/pd/formulas/${formulaId}/items`, {
        ingredient_name: newItem.ingredient_name,
        percentage: parseFloat(newItem.percentage),
        price_per_kg: priceInBRL,
        price_usd: newItem.price_usd !== "" ? parseFloat(newItem.price_usd) : null,
        fornecedor: newItem.fornecedor || "",
        phase: newItem.phase,
        function: newItem.function,
        catalog_id: newItem.catalog_id || null,
      });
      toast.success("Ingrediente adicionado!");
      setNewItem({ ingredient_name: "", percentage: "", price_per_kg: "", price_usd: "", price_currency: "BRL", fornecedor: "", phase: "", function: "", catalog_id: "" });
      setPendingCatalogItem(null);
      setShowSuggestions(false);
      onRefresh();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao adicionar"); }
  };

  const deleteItem = async (itemId) => {
    try { await api.delete(`/pd/formula-items/${itemId}`); onRefresh(); }
    catch (err) { toast.error("Erro ao remover"); }
  };

  const startEditItem = (item) => {
    setEditingItemId(item.id);
    setEditItemForm({
      ingredient_name: item.ingredient_name,
      fornecedor: item.fornecedor || "",
      percentage: String(item.percentage || ""),
      price_per_kg: String(item.price_per_kg || ""),
      price_usd: String(item.price_usd ?? ""),
      price_currency: "BRL",
    });
  };

  const cancelEditItem = () => setEditingItemId(null);

  const saveEditItem = async (formulaId) => {
    try {
      const formula = formulas.find(f => f.id === formulaId);
      const cotacao = formula?.cotacao_usd || 6.00;
      const rawPrice = parseFloat(editItemForm.price_per_kg) || 0;
      const priceInBRL = editItemForm.price_currency === "USD" ? rawPrice * cotacao : rawPrice;
      await api.put(`/pd/formula-items/${editingItemId}`, {
        ingredient_name: editItemForm.ingredient_name,
        fornecedor: editItemForm.fornecedor || "",
        percentage: parseFloat(editItemForm.percentage) || 0,
        price_per_kg: priceInBRL,
        price_usd: editItemForm.price_usd !== "" ? parseFloat(editItemForm.price_usd) : null,
      });
      toast.success("Item atualizado!");
      cancelEditItem();
      onRefresh();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao atualizar");
    }
  };

  const duplicateFormula = async (formulaId) => {
    try {
      await api.post(`/pd/formulas/${formulaId}/duplicate`);
      toast.success("Variação criada! Ajuste o ingrediente diferente.");
      onRefresh();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao duplicar"); }
  };

  const startEditConfig = (f) => {
    setEditingConfig(f.id);
    setConfigForm({
      volume: f.volume || "",
      volume_unit: f.volume_unit || "mL",
      indice_perdas: f.indice_perdas || 0,
      cotacao_usd: f.cotacao_usd || 6.00,
      fragrance_target: f.fragrance_target ?? "",
    });
  };

  const saveConfig = async (formulaId) => {
    try {
      const payload = {
        volume: parseFloat(configForm.volume) || 0,
        volume_unit: configForm.volume_unit,
        indice_perdas: parseFloat(configForm.indice_perdas) || 0,
        cotacao_usd: parseFloat(configForm.cotacao_usd) || 6.00,
      };
      if (configForm.fragrance_target !== "" && configForm.fragrance_target != null) {
        payload.fragrance_target = parseFloat(configForm.fragrance_target);
      }
      await api.put(`/pd/formulas/${formulaId}`, payload);
      toast.success("Configuração salva!");
      setEditingConfig(null);
      onRefresh();
    } catch (err) { toast.error("Erro ao salvar"); }
  };

  return (
    <div className="space-y-4">
      {/* Briefing técnico (CRM) — alvos para o P&D só preencher MPs/insumos */}
      {clientInfo && clientInfo._source === "crm_sample" && (
        <Card className="border-blue-200 dark:border-blue-900 bg-blue-50/30 dark:bg-blue-950/20" data-testid="formula-briefing-targets">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              Alvos do Briefing (CRM){clientInfo._variacao_codigo ? ` — Variação ${clientInfo._variacao_codigo}` : ""}
            </CardTitle>
            <p className="text-[11px] text-muted-foreground">
              Volume, fragrância e parâmetros já vieram da solicitação. P&D só precisa adicionar MPs/insumos/ingredientes.
            </p>
          </CardHeader>
          <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs pt-0">
            {req?.volume && (
              <div><span className="text-muted-foreground">Volume alvo:</span> <span className="font-medium">{req.volume}</span></div>
            )}
            {clientInfo.ph && (
              <div><span className="text-muted-foreground">pH alvo:</span> <span className="font-medium">{clientInfo.ph}</span></div>
            )}
            {clientInfo.textura_esperada && (
              <div className="col-span-2"><span className="text-muted-foreground">Textura:</span> <span className="font-medium">{clientInfo.textura_esperada}</span></div>
            )}
            {clientInfo.sensorial && (
              <div className="col-span-2"><span className="text-muted-foreground">Sensorial:</span> <span className="font-medium">{clientInfo.sensorial}</span></div>
            )}
            {clientInfo.aplicacao && (
              <div className="col-span-2"><span className="text-muted-foreground">Aplicação:</span> <span className="font-medium">{clientInfo.aplicacao}</span></div>
            )}
            {clientInfo.ativos_claims && (
              <div className="col-span-4"><span className="text-muted-foreground">Ativos / Claims:</span> <span className="font-medium">{clientInfo.ativos_claims}</span></div>
            )}
            {clientInfo.orcamento_projeto && (
              <div className="col-span-2"><span className="text-muted-foreground">Orçamento:</span> <span className="font-medium">{clientInfo.orcamento_projeto}</span></div>
            )}
          </CardContent>
        </Card>
      )}
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">Manipulação / Formulação ({formulas.length})</h3>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setShowImport(true)} className="gap-1.5" disabled={!canEdit}>
            <Copy className="h-3.5 w-3.5" /> Importar Fórmula
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)} className="gap-1.5" disabled={!canEdit}>
            <Plus className="h-3.5 w-3.5" /> Nova Versão
          </Button>
        </div>
      </div>

      <ImportFormulaDialog open={showImport} onOpenChange={setShowImport} devId={devId} onImported={onRefresh} />

      {showCreate && (
        <Card className="border-primary/50">
          <CardContent className="p-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Nome da Fórmula *</Label>
                <Input value={formulaName} onChange={e => setFormulaName(e.target.value)} placeholder="Ex: Aromatizante v1" />
              </div>
              <div>
                <Label>Volume</Label>
                <div className="flex gap-2">
                  <Input type="number" value={formulaVolume} onChange={e => setFormulaVolume(e.target.value)} placeholder="200" className="flex-1" />
                  <Select value={formulaVolumeUnit} onValueChange={setFormulaVolumeUnit}>
                    <SelectTrigger className="w-20"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="mL">mL</SelectItem>
                      <SelectItem value="L">L</SelectItem>
                      <SelectItem value="g">g</SelectItem>
                      <SelectItem value="kg">kg</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div>
                <Label>Índice de Perdas e Acréscimos (%)</Label>
                <Input type="number" step="0.1" value={formulaIndicePerdas} onChange={e => setFormulaIndicePerdas(e.target.value)} placeholder="10" />
              </div>
              <div>
                <Label>Cotação US$</Label>
                <Input type="number" step="0.01" value={formulaCotacao} onChange={e => setFormulaCotacao(e.target.value)} placeholder="6.00" />
              </div>
            </div>
            <div>
              <Label>Notas</Label>
              <Textarea value={formulaNotes} onChange={e => setFormulaNotes(e.target.value)} placeholder="Observações..." rows={2} />
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={createFormula} disabled={saving}>{saving ? "Criando..." : "Criar Fórmula"}</Button>
              <Button size="sm" variant="ghost" onClick={() => setShowCreate(false)}>Cancelar</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {formulas.map(f => {
        const items = f.items || [];
        const totalPct = items.reduce((s, it) => s + (it.percentage || 0), 0);
        const totalCostBrl = items.reduce((s, it) => s + (it.cost_brl || 0), 0);
        const totalPriceSum = items.reduce((s, it) => s + (it.price_per_kg || 0), 0);
        const isOk = Math.abs(totalPct - 100) < 0.01;
        const open = expandedFormula === f.id;
        
        const volume = f.volume || 0;
        const volumeUnit = f.volume_unit || "mL";
        const volumeKg = volumeUnit === "mL" ? volume / 1000 : (volumeUnit === "L" ? volume : (volumeUnit === "g" ? volume / 1000 : volume));
        const custoUnit = volumeKg > 0 ? totalCostBrl * volumeKg : totalCostBrl;
        const indicePerdas = f.indice_perdas || 0;
        const custoComPerdas = indicePerdas > 0 ? custoUnit * (1 + indicePerdas / 100) : custoUnit;

        return (
          <Card key={f.id} className={open ? "border-primary/30" : "hover:border-primary/20 transition-colors"}>
            <CardHeader className="pb-2 cursor-pointer" onClick={() => setExpandedFormula(open ? null : f.id)}>
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Badge variant="outline" className="text-xs font-mono">v{f.version}</Badge>
                  {f.name}
                  {f.locked && (
                    <Badge className="text-[10px] bg-amber-500/20 text-amber-700 border-amber-300 gap-1">
                      <Lock className="h-2.5 w-2.5" /> Registrada
                    </Badge>
                  )}
                  {f.version_justification && (
                    <span className="text-[10px] text-muted-foreground truncate max-w-xs" title={f.version_justification}>
                      "{f.version_justification.slice(0, 40)}..."
                    </span>
                  )}
                </CardTitle>
                <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                  {volume > 0 && (
                    <span className="text-xs text-muted-foreground">{volume} {volumeUnit}</span>
                  )}
                  <span className="text-xs font-bold text-green-600">
                    R$ {custoUnit.toFixed(2)}
                  </span>
                  <Badge variant="secondary" className="text-[10px]">{items.length} itens</Badge>
                  {canEdit && items.length > 0 && (
                    <Button size="sm" variant="ghost" className="h-7 text-xs gap-1 text-muted-foreground hover:text-foreground" onClick={() => duplicateFormula(f.id)} title="Copia todos os ingredientes para uma nova versão — ideal para variações de fragrância">
                      <Copy className="h-3 w-3" /> Duplicar
                    </Button>
                  )}
                  {canEdit && f.locked && (
                    <Button size="sm" variant="outline" className="h-7 text-xs gap-1 border-amber-300 hover:bg-amber-50" onClick={() => { setShowNewVersion(f); setNewVersionJustification(""); }} data-testid={`new-version-btn-${f.id}`}>
                      <RefreshCw className="h-3 w-3" /> Nova Versão
                    </Button>
                  )}
                </div>
              </div>
            </CardHeader>
            {open && (
              <CardContent className="pt-0 space-y-3">
                {/* Formula Config Header (like spreadsheet) */}
                <div className="bg-muted/50 rounded-lg p-3 border">
                  {editingConfig === f.id ? (
                    <div className="grid grid-cols-5 gap-3">
                      <div>
                        <Label className="text-[11px]">Volume</Label>
                        <div className="flex gap-1">
                          <Input type="number" value={configForm.volume} onChange={e => setConfigForm(p => ({ ...p, volume: e.target.value }))} className="h-8 text-sm" />
                          <Select value={configForm.volume_unit} onValueChange={v => setConfigForm(p => ({ ...p, volume_unit: v }))}>
                            <SelectTrigger className="w-16 h-8 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="mL">mL</SelectItem>
                              <SelectItem value="L">L</SelectItem>
                              <SelectItem value="g">g</SelectItem>
                              <SelectItem value="kg">kg</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div>
                        <Label className="text-[11px]">Índice Perdas (%)</Label>
                        <Input type="number" step="0.1" value={configForm.indice_perdas} onChange={e => setConfigForm(p => ({ ...p, indice_perdas: e.target.value }))} className="h-8 text-sm" />
                      </div>
                      <div>
                        <Label className="text-[11px]">Cotação US$</Label>
                        <Input type="number" step="0.01" value={configForm.cotacao_usd} onChange={e => setConfigForm(p => ({ ...p, cotacao_usd: e.target.value }))} className="h-8 text-sm" />
                      </div>
                      <div>
                        <Label className="text-[11px] text-purple-700">Target Fragrância (%)</Label>
                        <Input type="number" step="0.01" placeholder="ex: 2.50" value={configForm.fragrance_target} onChange={e => setConfigForm(p => ({ ...p, fragrance_target: e.target.value }))} className="h-8 text-sm" />
                      </div>
                      <div className="flex items-end gap-1">
                        <Button size="sm" className="h-8" onClick={() => saveConfig(f.id)}><Save className="h-3 w-3" /></Button>
                        <Button size="sm" variant="ghost" className="h-8" onClick={() => setEditingConfig(null)}><X className="h-3 w-3" /></Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-6 text-xs">
                        <span><b>Produto:</b> {clientInfo?.produto || req.project_name}</span>
                        <span><b>Cliente:</b> {clientInfo?.nome_cliente || req.client_name || "—"}</span>
                        <span><b>Volume:</b> {volume > 0 ? `${volume} ${volumeUnit}` : "—"}</span>
                        <span><b>Índice Perdas:</b> {indicePerdas > 0 ? `${indicePerdas}%` : "—"}</span>
                        <span><b>Cotação US$:</b> {(f.cotacao_usd || 6.00).toFixed(2)}</span>
                        {f.fragrance_target != null && (
                          <span className="text-purple-700"><b>Target Fragr.:</b> {f.fragrance_target.toFixed(2)}%</span>
                        )}
                      </div>
                      {canEdit && (
                        <Button size="sm" variant="ghost" className="h-7 text-xs gap-1" onClick={(e) => { e.stopPropagation(); startEditConfig(f); }}>
                          <Settings2 className="h-3 w-3" /> Config
                        </Button>
                      )}
                    </div>
                  )}
                </div>

                {f.notes && <p className="text-xs text-muted-foreground italic">{f.notes}</p>}

                {/* PD-08: Phase editor */}
                <div className="border rounded-md p-3 bg-muted/20">
                  <FormulaPhaseEditor formulaId={f.id} canEdit={canEdit} />
                </div>

                {/* Spreadsheet-like table with cost columns */}
                <div className="border rounded-md overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-[#0A0A0B] text-white text-xs">
                        <th className="text-left p-2 font-medium">Formulação</th>
                        <th className="text-left p-2 font-medium w-32">Fornecedor</th>
                        <th className="text-right p-2 font-medium w-24">%Fórmula</th>
                        <th className="text-right p-2 font-medium w-24">Qtd/Lote</th>
                        <th className="text-right p-2 font-medium w-28">Preço R$ (Kg)</th>
                        <th className="text-right p-2 font-medium w-28 text-yellow-300">Preço US$ (Kg)</th>
                        <th className="text-right p-2 font-medium w-24">Custo R$</th>
                        <th className="text-right p-2 font-medium w-28">Custo Kg/U$</th>
                        <th className="text-right p-2 font-medium w-24">% de Custo</th>
                        <th className="w-16"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map(item => {
                        const isEditingThis = canEdit && editingItemId === item.id;
                        const costPct = totalCostBrl > 0 ? (item.cost_brl / totalCostBrl * 100) : 0;
                        const qtyLote = volume > 0 ? (volume * (item.percentage || 0) / 100) : 0;
                        const qtyLabel = qtyLote > 0 ? `${qtyLote.toFixed(3)} ${volumeUnit}` : "—";

                        if (isEditingThis) {
                          return (
                            <tr key={item.id} className="border-t bg-blue-50/40 dark:bg-blue-950/10">
                              <td className="p-1.5">
                                <Input value={editItemForm.ingredient_name} onChange={e => setEditItemForm(p => ({ ...p, ingredient_name: e.target.value }))} className="h-7 text-xs" />
                              </td>
                              <td className="p-1.5">
                                <Input
                                  value={editItemForm.fornecedor}
                                  onChange={e => handleSupplierInput(e.target.value, setEditItemForm, editItemSuppliers)}
                                  className="h-7 text-xs w-24"
                                  placeholder="Fornecedor"
                                  list={editItemSuppliers.length > 0 ? `pd-edit-suppliers-${editingItemId}` : undefined}
                                />
                                {editItemSuppliers.length > 0 && (
                                  <datalist id={`pd-edit-suppliers-${editingItemId}`}>
                                    {editItemSuppliers.map((supplier) => (
                                      <option key={`${supplier.id}-${supplier.razao_social}`} value={supplier.razao_social}>
                                        {supplier.nome_fantasia ? `${supplier.razao_social} (${supplier.nome_fantasia})` : supplier.razao_social}
                                      </option>
                                    ))}
                                  </datalist>
                                )}
                              </td>
                              <td className="p-1.5">
                                <Input type="number" step="0.001" value={editItemForm.percentage} onChange={e => setEditItemForm(p => ({ ...p, percentage: e.target.value }))} className="h-7 text-xs w-20 text-right font-mono" />
                              </td>
                              <td className="p-2 text-right text-xs text-muted-foreground">—</td>
                              <td className="p-1.5">
                                <div className="flex gap-1">
                                  <Input type="number" step="0.01" value={editItemForm.price_per_kg} onChange={e => setEditItemForm(p => ({ ...p, price_per_kg: e.target.value }))} className="h-7 text-xs w-20 text-right font-mono" />
                                  <button type="button" onClick={() => setEditItemForm(p => ({ ...p, price_currency: p.price_currency === "USD" ? "BRL" : "USD" }))}
                                    className={`h-7 px-1.5 rounded text-[10px] font-bold border shrink-0 ${editItemForm.price_currency === "USD" ? "bg-blue-600 text-white border-blue-600" : "bg-muted text-muted-foreground border-border"}`}>
                                    {editItemForm.price_currency === "USD" ? "US$" : "R$"}
                                  </button>
                                </div>
                              </td>
                              <td className="p-1.5">
                                <Input type="number" step="0.01" value={editItemForm.price_usd} onChange={e => setEditItemForm(p => ({ ...p, price_usd: e.target.value }))} className="h-7 text-xs w-24 text-right font-mono border-yellow-300 focus:border-yellow-500" placeholder="US$" />
                              </td>
                              <td className="p-2 text-xs text-muted-foreground text-right">—</td>
                              <td className="p-2 text-xs text-muted-foreground text-right">—</td>
                              <td className="p-2 text-xs text-muted-foreground text-right">—</td>
                              <td className="p-1.5">
                                <div className="flex gap-1.5 justify-center">
                                  <button onClick={() => saveEditItem(f.id)} className="text-green-600 hover:text-green-700 transition-colors" title="Salvar"><Save className="h-3.5 w-3.5" /></button>
                                  <button onClick={cancelEditItem} className="text-muted-foreground hover:text-red-500 transition-colors" title="Cancelar"><X className="h-3.5 w-3.5" /></button>
                                </div>
                              </td>
                            </tr>
                          );
                        }

                        return (
                          <tr key={item.id} className="border-t hover:bg-muted/30">
                            <td className="p-2 font-medium">{item.ingredient_name}</td>
                            <td className="p-2 text-xs text-muted-foreground">{item.fornecedor || "—"}</td>
                            <td className="p-2 text-right font-mono text-xs">{(item.percentage || 0).toFixed(3)}</td>
                            <td className="p-2 text-right font-mono text-xs text-blue-600">{qtyLabel}</td>
                            <td className="p-2 text-right font-mono text-xs">{(item.price_per_kg || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono text-xs">
                              {item.price_usd != null ? (
                                <div>
                                  <div className="text-yellow-700 font-semibold">{item.price_usd.toFixed(2)}</div>
                                  {item.cost_brl_via_cambio != null && (
                                    <div className="text-[10px] text-muted-foreground">= R$ {item.cost_brl_via_cambio.toFixed(2)}</div>
                                  )}
                                </div>
                              ) : "—"}
                            </td>
                            <td className="p-2 text-right font-mono text-xs">{(item.cost_brl || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono text-xs">{(item.cost_kg_usd || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono text-xs">{costPct.toFixed(2)}%</td>
                            <td className="p-2 text-center">
                              {canEdit && (
                                <div className="flex gap-1.5 justify-center">
                                  <button onClick={() => startEditItem(item)} className="text-muted-foreground hover:text-blue-500 transition-colors" title="Editar"><Pencil className="h-3.5 w-3.5" /></button>
                                  <button onClick={() => deleteItem(item.id)} className="text-muted-foreground hover:text-red-500 transition-colors" title="Remover"><Trash2 className="h-3.5 w-3.5" /></button>
                                </div>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                      {items.length === 0 && (
                        <tr><td colSpan={10} className="p-4 text-center text-xs text-muted-foreground">Nenhum ingrediente. Adicione abaixo.</td></tr>
                      )}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-2 bg-muted/30 font-bold">
                        <td className="p-2 text-xs">Custo Unit.</td>
                        <td className="p-2"></td>
                        <td className={`p-2 text-right font-mono text-xs ${isOk ? "text-green-600" : "text-amber-600"}`}>{totalPct.toFixed(3)}</td>
                        <td className="p-2 text-right font-mono text-xs text-blue-600">{volume > 0 ? `${volume} ${volumeUnit}` : "—"}</td>
                        <td className="p-2 text-right font-mono text-xs">{totalPriceSum.toFixed(2)}</td>
                        <td className="p-2"></td>
                        <td className="p-2 text-right font-mono text-xs bg-muted">
                          <span className="text-green-700 font-bold">R$ {custoUnit.toFixed(2)}</span>
                        </td>
                        <td className="p-2"></td>
                        <td className="p-2 text-right font-mono text-xs">100,00%</td>
                        <td className="p-2"></td>
                      </tr>
                      {indicePerdas > 0 && (
                        <tr className="bg-muted/20">
                          <td colSpan={4} className="p-2 text-xs text-muted-foreground">Com índice de perdas ({indicePerdas}%)</td>
                          <td className="p-2"></td>
                          <td className="p-2 text-right font-mono text-xs font-bold text-orange-600">R$ {custoComPerdas.toFixed(2)}</td>
                          <td colSpan={4}></td>
                        </tr>
                      )}
                    </tfoot>
                  </table>
                </div>

                {/* Add ingredient row */}
                {canEdit && (
                  <div className="flex gap-2 items-end p-3 bg-muted/30 rounded-lg border border-dashed relative">
                    <div className="flex-1 relative">
                      <Label className="text-[11px] text-muted-foreground flex items-center gap-1">
                        Ingrediente
                        {newItem.catalog_id && (
                          <Badge className="text-[9px] h-3.5 px-1 bg-green-500/20 text-green-700 border-green-300">do banco</Badge>
                        )}
                      </Label>
                      <Input value={newItem.ingredient_name}
                        onChange={e => {
                          setNewItem(p => ({ ...p, ingredient_name: e.target.value, catalog_id: "", fornecedor: "" }));
                          setPendingCatalogItem(null);
                          setShowSuggestions(true);
                        }}
                        onFocus={() => setShowSuggestions(true)}
                        onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                        placeholder={ingredientOptions.length > 0 ? "Digite ou escolha uma MP cadastrada..." : "Nome do ingrediente"}
                        className="h-8 text-sm" />
                      {showSuggestions && filteredCatalog.length > 0 && (
                        <div className="absolute top-full left-0 right-0 mt-1 bg-popover border rounded-md shadow-lg z-50 max-h-64 overflow-y-auto">
                          {filteredCatalog.slice(0, 15).map(cat => {
                            const temFornecedores = (cat.fornecedores || []).length > 0;
                            const precos = (cat.fornecedores || [])
                              .map((supplier) => toFiniteNumber(supplier.preco_rs_kg))
                              .filter((price) => price !== null);
                            const precoMin = precos.length > 0
                              ? Math.min(...precos)
                              : toFiniteNumber(cat.preco_rs_kg);
                            return (
                              <button
                                key={cat.option_key}
                                type="button"
                                onMouseDown={(e) => { e.preventDefault(); pickFromCatalog(cat); }}
                                className="w-full text-left px-3 py-2 hover:bg-muted border-b last:border-0 flex items-center justify-between gap-2"
                              >
                                <div className="min-w-0">
                                  <div className="text-sm font-medium truncate">{cat.nome}</div>
                                  <div className="text-[10px] text-muted-foreground truncate">
                                    {cat.inci && <>INCI: {cat.inci}</>}
                                    {cat.codigo_interno && <> · {cat.codigo_interno}</>}
                                    {temFornecedores ? <> · {cat.fornecedores.length} fornecedor(es)</> : cat.fornecedor ? <> · {cat.fornecedor}</> : null}
                                    {cat.categoria && <> · {cat.categoria}</>}
                                  </div>
                                </div>
                                <span className="text-xs font-mono font-semibold shrink-0 text-green-700">
                                  {precoMin !== null
                                    ? <>{temFornecedores ? "a partir de " : ""}R$ {precoMin.toFixed(2)}/{cat.unidade || "kg"}</>
                                    : "sem preço"}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                      {pendingCatalogItem && (
                        <div className="mt-1 border rounded-md bg-popover shadow-md p-2 z-40">
                          <div className="text-[10px] font-semibold text-muted-foreground mb-1.5 uppercase tracking-wide flex items-center justify-between">
                            <span>Selecionar fornecedor — {pendingCatalogItem.nome}</span>
                          </div>
                          <div className="space-y-1">
                            {pendingCatalogItem.fornecedores.map((sup, idx) => (
                              <button
                                key={idx}
                                type="button"
                                className={`w-full text-left px-2 py-1.5 rounded border text-xs flex items-center justify-between gap-2 transition-colors ${supplierRankColor(idx)}`}
                                onClick={() => {
                                  setNewItem(p => ({ ...p, fornecedor: sup.nome, price_per_kg: String(sup.preco_rs_kg || 0), price_currency: sup.moeda || "BRL" }));
                                  setPendingCatalogItem(null);
                                }}
                              >
                                <span className="font-medium">{sup.nome}{sup.codigo && <span className="text-[10px] ml-1 opacity-70">· {sup.codigo}</span>}</span>
                                <span className="font-mono font-semibold shrink-0">
                                  {sup.moeda === "USD" ? "US$" : "R$"} {(sup.preco_rs_kg || 0).toFixed(2)}/{pendingCatalogItem.unidade || "kg"}
                                </span>
                              </button>
                            ))}
                          </div>
                          <button type="button" className="mt-1.5 text-[10px] text-muted-foreground hover:text-foreground underline" onClick={() => setPendingCatalogItem(null)}>
                            ← inserir preço manualmente
                          </button>
                        </div>
                      )}
                    </div>
                    <div className="w-28">
                      <Label className="text-[11px] text-muted-foreground">Fornecedor</Label>
                      <Input
                        value={newItem.fornecedor}
                        onChange={e => handleSupplierInput(e.target.value, setNewItem, newItemSuppliers)}
                        placeholder="Fornecedor"
                        className="h-8 text-sm"
                        list={newItemSuppliers.length > 0 ? `pd-formula-suppliers-${devId}` : undefined}
                      />
                      {newItemSuppliers.length > 0 && (
                        <datalist id={`pd-formula-suppliers-${devId}`}>
                          {newItemSuppliers.map((supplier) => (
                            <option key={`${supplier.id}-${supplier.razao_social}`} value={supplier.razao_social}>
                              {supplier.nome_fantasia ? `${supplier.razao_social} (${supplier.nome_fantasia})` : supplier.razao_social}
                            </option>
                          ))}
                        </datalist>
                      )}
                    </div>
                    <div className="w-20">
                      <Label className="text-[11px] text-muted-foreground"><FieldHint hint="Percentual em massa deste ingrediente na fórmula total. A soma de todos os ingredientes deve ser 100%.">%Fórmula</FieldHint></Label>
                      <Input type="number" step="0.001" value={newItem.percentage}
                        onChange={e => setNewItem(p => ({ ...p, percentage: e.target.value }))}
                        placeholder="0.000" className="h-8 text-sm font-mono" />
                    </div>
                    <div className="w-36">
                      <Label className="text-[11px] text-muted-foreground">
                        Preço {newItem.price_currency === "USD" ? "US$/Kg" : "R$/Kg"}
                      </Label>
                      <div className="flex gap-1">
                        <Input type="number" step="0.01" value={newItem.price_per_kg}
                          onChange={e => setNewItem(p => ({ ...p, price_per_kg: e.target.value, catalog_id: "" }))}
                          placeholder="0.00" className="h-8 text-sm font-mono" />
                        <button
                          type="button"
                          onClick={() => setNewItem(p => ({ ...p, price_currency: p.price_currency === "USD" ? "BRL" : "USD" }))}
                          className={`h-8 px-2 rounded text-[10px] font-bold border shrink-0 transition-colors ${newItem.price_currency === "USD" ? "bg-blue-600 text-white border-blue-600" : "bg-muted text-muted-foreground border-border hover:bg-muted/80"}`}
                          title={newItem.price_currency === "USD" ? `Cotação: R$ ${(formulas.find(f2 => f2.id === f.id)?.cotacao_usd || 6).toFixed(2)}` : "Clique para inserir em US$"}
                        >
                          {newItem.price_currency === "USD" ? "US$" : "R$"}
                        </button>
                      </div>
                      {newItem.price_currency === "USD" && newItem.price_per_kg && (
                        <div className="text-[10px] text-blue-600 mt-0.5">
                          = R$ {((parseFloat(newItem.price_per_kg) || 0) * (formulas.find(f2 => f2.id === f.id)?.cotacao_usd || 6)).toFixed(2)}/Kg
                        </div>
                      )}
                    </div>
                    <div className="w-28">
                      <Label className="text-[11px] text-muted-foreground text-yellow-700">Preço US$/Kg</Label>
                      <Input type="number" step="0.01" value={newItem.price_usd}
                        onChange={e => setNewItem(p => ({ ...p, price_usd: e.target.value }))}
                        placeholder="opcional" className="h-8 text-sm font-mono border-yellow-300" />
                    </div>
                    <Button size="sm" className="h-8 gap-1" onClick={() => addItem(f.id)}>
                      <Plus className="h-3 w-3" /> Adicionar
                    </Button>
                  </div>
                )}
              </CardContent>
            )}
          </Card>
        );
      })}

      {formulas.length === 0 && !showCreate && (
        <EmptyState icon={Beaker} title="Nenhuma fórmula criada" subtitle="Crie a primeira versão da manipulação" />
      )}
      {/* Nova Versão Dialog */}
      {showNewVersion && (
        <Dialog open onOpenChange={() => setShowNewVersion(null)}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <RefreshCw className="h-4 w-4 text-amber-500" />
                Criar Nova Versão da Fórmula
              </DialogTitle>
              <DialogDescription>
                A fórmula <strong>v{showNewVersion.version}</strong> está registrada e bloqueada (RN-BF-01).
                Uma nova versão será criada copiando os ingredientes atuais. A versão anterior permanece imutável.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <div>
                <Label className="text-sm font-medium">Justificativa <span className="text-red-500">*</span></Label>
                <Textarea
                  value={newVersionJustification}
                  onChange={e => setNewVersionJustification(e.target.value)}
                  placeholder="Descreva o motivo da alteração da fórmula (mínimo 10 caracteres)..."
                  rows={4}
                  className="mt-1"
                  data-testid="new-version-justification"
                />
                <p className="text-xs text-muted-foreground mt-1">{newVersionJustification.length}/10 mínimo</p>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowNewVersion(null)}>Cancelar</Button>
              <Button onClick={createNewVersion} disabled={creatingVersion || newVersionJustification.trim().length < 10} data-testid="confirm-new-version-btn">
                {creatingVersion ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
                Criar v{(showNewVersion.version || 1) + 1}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      <SampleBatchSection devId={devId} formulas={formulas} onRefresh={onRefresh} canEdit={canEdit} />
    </div>
  );
}

/* ============ SAMPLE BATCH COMPONENTS ============ */

const SAMPLE_BATCH_BASE_STATUS_LABELS = {
  ativa: "Base ativa",
  bloqueada: "Base bloqueada",
  encerrada: "Base encerrada",
};

const SAMPLE_BATCH_QUALITY_LABELS = {
  aprovada: "Qualidade aprovada",
  pendente: "Qualidade pendente",
  reprovada: "Qualidade reprovada",
};

const SAMPLE_BATCH_SCOPE_LABELS = {
  cor: "Cor",
  ativo: "Ativo",
  fragrancia: "Fragrancia",
};

function computeSampleBatchMetrics(batch = {}) {
  const volumePerSampleMl = Number(batch.volume_base_ml) || 0;
  const variants = Array.isArray(batch.variantes) ? batch.variantes : [];
  const baseTotalVolumeMl = Number(batch.base_total_volume_ml) || (volumePerSampleMl * Math.max(variants.length, 1));
  const maxDerivations = Number(batch.max_derivacoes) > 0 ? Number(batch.max_derivacoes) : null;
  const lossPct = Math.max(0, Number(batch.perda_operacional_percent) || 0);
  const usableVolumeMl = Math.max(baseTotalVolumeMl * (1 - (lossPct / 100)), 0);
  const byVolume = volumePerSampleMl > 0 ? Math.floor(usableVolumeMl / volumePerSampleMl) : 0;
  const capacity = maxDerivations == null ? byVolume : Math.min(byVolume, maxDerivations);
  const derivadasCount = variants.length;
  const remaining = Math.max(capacity - derivadasCount, 0);
  const volumeConsumedMl = derivadasCount * volumePerSampleMl;
  const volumeAvailableMl = Math.max(baseTotalVolumeMl - volumeConsumedMl, 0);
  const validade = batch.validade_base ? new Date(`${batch.validade_base}T00:00:00`) : null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const blockedReasons = [];
  if (validade && !Number.isNaN(validade.getTime()) && validade < today) blockedReasons.push("Validade expirada");
  if ((batch.status_base || "ativa") !== "ativa") blockedReasons.push(SAMPLE_BATCH_BASE_STATUS_LABELS[batch.status_base] || "Base indisponivel");
  if ((batch.status_qualidade || "aprovada") !== "aprovada") blockedReasons.push(SAMPLE_BATCH_QUALITY_LABELS[batch.status_qualidade] || "Qualidade nao aprovada");
  if (remaining <= 0) blockedReasons.push("Capacidade de derivacao esgotada");
  if (volumePerSampleMl > 0 && volumeAvailableMl < volumePerSampleMl) blockedReasons.push("Volume insuficiente para nova amostra");

  return {
    volumePerSampleMl,
    baseTotalVolumeMl,
    maxDerivations,
    lossPct,
    capacity,
    derivadasCount,
    remaining,
    volumeConsumedMl,
    volumeAvailableMl,
    blockedReasons,
    blocked: blockedReasons.length > 0,
  };
}

function SampleBatchEditor({ devId, formulas, initial, onSave, onClose }) {
  const { ingredientOptions, getSuppliersForIngredient } = usePdMaterialLibrary();
  const emptyVariante = () => ({ id: crypto.randomUUID(), nome: "", versao: 1, overrides: [], notas: "" });
  const [form, setForm] = useState(initial ? {
    nome: initial.nome || "",
    formula_base_id: initial.formula_base_id || (formulas[0]?.id || ""),
    volume_base_ml: initial.volume_base_ml || 15,
    base_total_volume_ml: initial.base_total_volume_ml || ((initial.volume_base_ml || 15) * Math.max((initial.variantes || []).length, 1)),
    max_derivacoes: initial.max_derivacoes ?? "",
    perda_operacional_percent: initial.perda_operacional_percent || 0,
    validade_base: initial.validade_base || "",
    condicoes_armazenamento: initial.condicoes_armazenamento || "",
    status_base: initial.status_base || "ativa",
    status_qualidade: initial.status_qualidade || "aprovada",
    allowed_change_scopes: initial.allowed_change_scopes || ["cor", "ativo", "fragrancia"],
    base_reference_ingredients: initial.base_reference_ingredients || ["Agua", "Alcool", "Acido hialuronico"],
    notas: initial.notas || "",
    variantes: (initial.variantes || []).map(v => ({
      id: v.id || crypto.randomUUID(),
      nome: v.nome || "",
      versao: v.versao || 1,
      overrides: (v.overrides || []).map(o => ({ ...o })),
      notas: v.notas || "",
    })),
  } : {
    nome: "",
    formula_base_id: formulas[0]?.id || "",
    volume_base_ml: 15,
    base_total_volume_ml: 150,
    max_derivacoes: "",
    perda_operacional_percent: 0,
    validade_base: "",
    condicoes_armazenamento: "",
    status_base: "ativa",
    status_qualidade: "aprovada",
    allowed_change_scopes: ["cor", "ativo", "fragrancia"],
    base_reference_ingredients: ["Agua", "Alcool", "Acido hialuronico"],
    notas: "",
    variantes: [emptyVariante()],
  });
  const [saving, setSaving] = useState(false);
  const [baseItems, setBaseItems] = useState([]);
  const [loadingItems, setLoadingItems] = useState(false);

  const getFornecedoresForIngredient = (ingredientName) => {
    return getSuppliersForIngredient(ingredientName);
  };

  useEffect(() => {
    if (!form.formula_base_id) return;
    setLoadingItems(true);
    api.get(`/pd/formulas/${form.formula_base_id}/items`)
      .then(({ data }) => setBaseItems(Array.isArray(data) ? data : []))
      .catch(() => setBaseItems([]))
      .finally(() => setLoadingItems(false));
  }, [form.formula_base_id]);

  const batchMetrics = useMemo(() => computeSampleBatchMetrics({
    ...form,
    max_derivacoes: form.max_derivacoes === "" ? null : form.max_derivacoes,
  }), [form]);

  const setVariante = (idx, updates) => setForm(f => {
    const v = [...f.variantes];
    v[idx] = { ...v[idx], ...updates };
    return { ...f, variantes: v };
  });

  const addVariante = () => {
    if (batchMetrics.remaining <= 0) {
      toast.error("A base nao suporta novas derivacoes com os limites atuais");
      return;
    }
    setForm(f => ({ ...f, variantes: [...f.variantes, emptyVariante()] }));
  };

  const removeVariante = (idx) => setForm(f => ({ ...f, variantes: f.variantes.filter((_, i) => i !== idx) }));

  const toggleChangeScope = (scope) => setForm(f => {
    const selected = new Set(f.allowed_change_scopes || []);
    if (selected.has(scope)) selected.delete(scope);
    else selected.add(scope);
    const next = [...selected];
    return { ...f, allowed_change_scopes: next.length ? next : [scope] };
  });

  const addOverride = (vIdx) => setVariante(vIdx, {
    overrides: [...(form.variantes[vIdx]?.overrides || []), { ingredient_name_base: "", ingredient_name: "", percentage: 0, fornecedor: "" }]
  });

  const updateOverride = (vIdx, oIdx, field, value) => {
    const v = [...form.variantes];
    const overrides = v[vIdx].overrides.map((o, i) => i === oIdx ? { ...o, [field]: value } : o);
    v[vIdx] = { ...v[vIdx], overrides };
    setForm(f => ({ ...f, variantes: v }));
  };

  const removeOverride = (vIdx, oIdx) => {
    const v = [...form.variantes];
    v[vIdx] = { ...v[vIdx], overrides: v[vIdx].overrides.filter((_, i) => i !== oIdx) };
    setForm(f => ({ ...f, variantes: v }));
  };

  const handleSave = async () => {
    if (!form.nome.trim()) { toast.error("Nome do lote é obrigatório"); return; }
    if (!form.formula_base_id) { toast.error("Selecione a fórmula base"); return; }
    if ((form.variantes || []).length === 0) { toast.error("Adicione ao menos uma variante"); return; }

    const sanitizedVariantes = [];
    for (let index = 0; index < (form.variantes || []).length; index += 1) {
      const variante = form.variantes[index];
      const nomeVariante = variante.nome?.trim() || `Variante ${index + 1}`;
      const sanitizedOverrides = [];

      for (const override of variante.overrides || []) {
        const ingredientBase = override.ingredient_name_base?.trim() || "";
        const ingredientName = override.ingredient_name?.trim() || "";
        const fornecedor = override.fornecedor?.trim() || "";
        const percentage = parseFloat(override.percentage) || 0;
        const isEmptyOverride = !ingredientBase && !ingredientName && !fornecedor && percentage === 0;

        if (isEmptyOverride) continue;
        if (!ingredientBase || !ingredientName) {
          toast.error(`Preencha base e MP substituta em ${nomeVariante}`);
          return;
        }
        if (percentage <= 0) {
          toast.error(`Informe um percentual válido para ${ingredientName} em ${nomeVariante}`);
          return;
        }

        sanitizedOverrides.push({
          ingredient_name_base: ingredientBase,
          ingredient_name: ingredientName,
          percentage,
          fornecedor,
        });
      }

      sanitizedVariantes.push({
        ...variante,
        nome: nomeVariante,
        notas: variante.notas || "",
        overrides: sanitizedOverrides,
      });
    }

    const payload = {
      ...form,
      nome: form.nome.trim(),
      max_derivacoes: form.max_derivacoes === "" ? null : Number(form.max_derivacoes),
      base_total_volume_ml: Number(form.base_total_volume_ml) || 0,
      perda_operacional_percent: Number(form.perda_operacional_percent) || 0,
      notas: form.notas || "",
      allowed_change_scopes: form.allowed_change_scopes || ["cor", "ativo", "fragrancia"],
      base_reference_ingredients: form.base_reference_ingredients || ["Agua", "Alcool", "Acido hialuronico"],
      variantes: sanitizedVariantes,
    };

    setSaving(true);
    try {
      await onSave(payload);
      onClose();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao salvar lote");
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <Label className="text-xs font-medium">Nome do Lote <span className="text-red-500">*</span></Label>
          <Input value={form.nome} onChange={e => setForm(f => ({ ...f, nome: e.target.value }))} placeholder="Ex: Lote Fragrâncias Jun/2026" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs font-medium">Volume da Amostra (mL)</Label>
          <Input type="number" value={form.volume_base_ml} onChange={e => setForm(f => ({ ...f, volume_base_ml: parseFloat(e.target.value) || 0 }))} />
          <p className="text-[10px] text-muted-foreground">Volume de cada amostra a elaborar no lab — não o volume do produto final (padrão: 15 mL)</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="space-y-1">
          <Label className="text-xs font-medium">Volume total da base (mL)</Label>
          <Input type="number" value={form.base_total_volume_ml} onChange={e => setForm(f => ({ ...f, base_total_volume_ml: parseFloat(e.target.value) || 0 }))} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs font-medium">MÃ¡x. derivaÃ§Ãµes</Label>
          <Input type="number" value={form.max_derivacoes} onChange={e => setForm(f => ({ ...f, max_derivacoes: e.target.value }))} placeholder="Sem limite" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs font-medium">Perda operacional (%)</Label>
          <Input type="number" step="0.01" value={form.perda_operacional_percent} onChange={e => setForm(f => ({ ...f, perda_operacional_percent: parseFloat(e.target.value) || 0 }))} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs font-medium">Validade da base</Label>
          <Input type="date" value={form.validade_base} onChange={e => setForm(f => ({ ...f, validade_base: e.target.value }))} />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="space-y-1">
          <Label className="text-xs font-medium">Status da base</Label>
          <Select value={form.status_base} onValueChange={v => setForm(f => ({ ...f, status_base: v }))}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="ativa">Ativa</SelectItem>
              <SelectItem value="bloqueada">Bloqueada</SelectItem>
              <SelectItem value="encerrada">Encerrada</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs font-medium">Status da qualidade</Label>
          <Select value={form.status_qualidade} onValueChange={v => setForm(f => ({ ...f, status_qualidade: v }))}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="aprovada">Aprovada</SelectItem>
              <SelectItem value="pendente">Pendente</SelectItem>
              <SelectItem value="reprovada">Reprovada</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs font-medium">Armazenamento</Label>
          <Input value={form.condicoes_armazenamento} onChange={e => setForm(f => ({ ...f, condicoes_armazenamento: e.target.value }))} placeholder="Ex: 25C, ao abrigo da luz" />
        </div>
      </div>

      <div className={`rounded-lg border p-3 ${batchMetrics.blocked ? "border-amber-300 bg-amber-50" : "border-emerald-200 bg-emerald-50/60"}`}>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="outline">Derivadas: {batchMetrics.derivadasCount}/{batchMetrics.capacity || 0}</Badge>
          <Badge variant="outline">Saldo: {batchMetrics.volumeAvailableMl.toFixed(1)} mL</Badge>
          <Badge variant="outline">Consumo: {batchMetrics.volumeConsumedMl.toFixed(1)} mL</Badge>
          {batchMetrics.maxDerivations != null && <Badge variant="outline">Limite manual: {batchMetrics.maxDerivations}</Badge>}
        </div>
        {batchMetrics.blocked ? (
          <p className="text-xs text-amber-700 mt-2">{batchMetrics.blockedReasons.join(" · ")}</p>
        ) : (
          <p className="text-xs text-emerald-700 mt-2">A base ainda suporta {batchMetrics.remaining} nova(s) derivaÃ§Ã£o(Ãµes).</p>
        )}
      </div>

      <div className="rounded-lg border bg-muted/20 p-3 space-y-3">
        <div>
          <Label className="text-xs font-medium">Base fixa de referencia</Label>
          <Input
            value={(form.base_reference_ingredients || []).join(", ")}
            onChange={e => setForm(f => ({ ...f, base_reference_ingredients: e.target.value.split(",").map(v => v.trim()).filter(Boolean) }))}
            className="mt-1 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs font-medium">Mudancas permitidas nas derivadas</Label>
          <div className="mt-2 flex flex-wrap gap-2">
            {["cor", "ativo", "fragrancia"].map(scope => (
              <Button
                key={scope}
                type="button"
                variant={(form.allowed_change_scopes || []).includes(scope) ? "default" : "outline"}
                size="sm"
                onClick={() => toggleChangeScope(scope)}
                className="h-7 text-xs"
              >
                {SAMPLE_BATCH_SCOPE_LABELS[scope]}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-1">
        <Label className="text-xs font-medium">Fórmula Base <span className="text-red-500">*</span></Label>
        <Select value={form.formula_base_id} onValueChange={v => setForm(f => ({ ...f, formula_base_id: v }))}>
          <SelectTrigger><SelectValue placeholder="Selecione a fórmula base..." /></SelectTrigger>
          <SelectContent>
            {formulas.map(f => (
              <SelectItem key={f.id} value={f.id}>v{f.version} — {f.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {loadingItems && <p className="text-xs text-muted-foreground">Carregando ingredientes...</p>}
        {baseItems.length > 0 && (
          <p className="text-xs text-muted-foreground">{baseItems.length} ingredientes na fórmula base</p>
        )}
      </div>

      <div className="space-y-1">
        <Label className="text-xs font-medium">Observações do Lote</Label>
        <Textarea value={form.notas} onChange={e => setForm(f => ({ ...f, notas: e.target.value }))} placeholder="Observações gerais sobre este lote..." rows={2} />
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <Label className="text-sm font-semibold flex items-center gap-1.5"><GitBranch className="h-4 w-4 text-violet-500" />Variantes</Label>
          <Button variant="outline" size="sm" onClick={addVariante} disabled={batchMetrics.remaining <= 0} className="h-7 text-xs gap-1"><Plus className="h-3 w-3" />Adicionar</Button>
        </div>

        {form.variantes.map((v, vIdx) => (
          <div key={v.id} className="border rounded-lg p-3 space-y-3 bg-muted/30">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="flex items-center justify-center h-6 w-6 rounded-full bg-violet-100 text-violet-700 text-xs font-bold flex-shrink-0">{vIdx + 1}</div>
              <Input
                value={v.nome}
                onChange={e => setVariante(vIdx, { nome: e.target.value })}
                placeholder={`Nome da variante ${vIdx + 1} (ex: Rosa, Floral, sem frag.)`}
                className="h-8 min-w-0 text-sm sm:flex-1"
              />
              <Input
                type="number"
                value={v.versao}
                onChange={e => setVariante(vIdx, { versao: parseInt(e.target.value) || 1 })}
                className="h-8 w-full text-sm sm:w-20"
                placeholder="v"
                min={1}
              />
              {form.variantes.length > 1 && (
                <button onClick={() => removeVariante(vIdx)} className="text-muted-foreground hover:text-red-500 transition-colors">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground font-medium">Substituições de ingredientes</span>
                <Button variant="ghost" size="sm" onClick={() => addOverride(vIdx)} className="h-6 text-xs gap-1 text-violet-600 hover:text-violet-700">
                  <Plus className="h-3 w-3" />Substituição
                </Button>
              </div>
              {v.overrides.length === 0 && (
                <p className="text-xs text-muted-foreground italic py-1">Sem substituições — todos os ingredientes seguem a fórmula base.</p>
              )}
              {v.overrides.map((o, oIdx) => {
                const filteredFornecedores = getFornecedoresForIngredient(o.ingredient_name);
                return (
                  <div key={oIdx} className="border border-border rounded-md p-2 space-y-1.5 bg-background">
                    <div className="grid grid-cols-1 items-center gap-1.5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto]">
                      <Select value={o.ingredient_name_base} onValueChange={val => updateOverride(vIdx, oIdx, "ingredient_name_base", val)}>
                        <SelectTrigger className="h-8 min-w-0 text-xs"><SelectValue placeholder="Substituir..." /></SelectTrigger>
                        <SelectContent>
                          {baseItems.map(it => <SelectItem key={it.id} value={it.ingredient_name}>{it.ingredient_name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                      <ChevronRight className="hidden h-3 w-3 text-muted-foreground sm:block" />
                      {ingredientOptions.length > 0 ? (
                        <Select value={o.ingredient_name} onValueChange={val => {
                          const v2 = [...form.variantes];
                          v2[vIdx] = { ...v2[vIdx], overrides: v2[vIdx].overrides.map((ov, i) => i === oIdx ? { ...ov, ingredient_name: val, fornecedor: "" } : ov) };
                          setForm(f => ({ ...f, variantes: v2 }));
                        }}>
                          <SelectTrigger className="h-8 min-w-0 text-xs"><SelectValue placeholder="MP substituta..." /></SelectTrigger>
                          <SelectContent>
                            {ingredientOptions.map(it => (
                              <SelectItem key={it.option_key} value={it.nome}>
                                {it.nome}{it.codigo_interno ? ` · ${it.codigo_interno}` : ""}{it.fornecedores?.length ? ` · ${it.fornecedores.length} forn.` : ""}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <Input value={o.ingredient_name} onChange={e => updateOverride(vIdx, oIdx, "ingredient_name", e.target.value)} placeholder="Novo ingrediente" className="h-8 min-w-0 text-xs" />
                      )}
                      <button onClick={() => removeOverride(vIdx, oIdx)} className="text-muted-foreground hover:text-red-500 transition-colors flex-shrink-0">
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                    <div className="grid grid-cols-[minmax(0,1fr)_auto_88px] items-center gap-1.5">
                      <Select value={o.fornecedor} onValueChange={val => updateOverride(vIdx, oIdx, "fornecedor", val)}>
                        <SelectTrigger className="h-8 min-w-0 text-xs"><SelectValue placeholder="Fornecedor..." /></SelectTrigger>
                        <SelectContent>
                          {filteredFornecedores.map(f => (
                            <SelectItem key={`${f.id}-${f.razao_social}`} value={f.razao_social}>
                              {f.razao_social}{f.nome_fantasia ? ` (${f.nome_fantasia})` : ""}{f.status ? ` · ${f.status}` : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <span className="text-xs text-muted-foreground flex-shrink-0">%</span>
                      <Input type="number" step="0.001" value={o.percentage} onChange={e => updateOverride(vIdx, oIdx, "percentage", parseFloat(e.target.value) || 0)} className="h-7 text-xs w-[80px] flex-shrink-0" />
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="space-y-1">
              <Textarea value={v.notas} onChange={e => setVariante(vIdx, { notas: e.target.value })} placeholder="Notas desta variante..." rows={1} className="text-xs" />
            </div>
          </div>
        ))}
      </div>

      <div className="flex justify-end gap-2 pt-2 border-t">
        <Button variant="outline" onClick={onClose}>Cancelar</Button>
        <Button onClick={handleSave} disabled={saving} className="gap-1.5">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Salvar Lote
        </Button>
      </div>
    </div>
  );
}

function fmtQty(pct, volumeMl) {
  const g = (pct / 100) * volumeMl;
  if (g === 0) return "0,000 g";
  if (g < 0.1) return `${(g * 1000).toFixed(0)} mg`;
  if (g < 10) return `${g.toFixed(3)} g`;
  return `${g.toFixed(2)} g`;
}

function SampleBatchCard({ batch, formulas, onEdit, onDelete, canEdit }) {
  const [baseItems, setBaseItems] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [showComparativo, setShowComparativo] = useState(false);
  const metrics = useMemo(() => computeSampleBatchMetrics(batch), [batch]);

  useEffect(() => {
    if (!expanded || !batch.formula_base_id) return;
    api.get(`/pd/formulas/${batch.formula_base_id}/items`)
      .then(({ data }) => setBaseItems(Array.isArray(data) ? data : []))
      .catch(() => setBaseItems([]));
  }, [expanded, batch.formula_base_id]);

  const baseFormula = formulas.find(f => f.id === batch.formula_base_id);
  const variantes = batch.variantes || [];
  const volumeMl = batch.volume_base_ml || 15;

  const variableSlots = useMemo(() => {
    return new Set((batch.variantes || []).flatMap(v => (v.overrides || []).map(o => o.ingredient_name_base).filter(Boolean)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch.variantes]);

  // Resolve all ingredients for a given variant (overrides applied)
  const resolveVariantItems = useCallback((v) => {
    return baseItems.map(baseItem => {
      const ov = (v.overrides || []).find(o => o.ingredient_name_base === baseItem.ingredient_name);
      if (ov) {
        return {
          ...baseItem,
          ingredient_name: ov.ingredient_name || baseItem.ingredient_name,
          percentage: ov.percentage,
          fornecedor: ov.fornecedor || baseItem.fornecedor,
          is_substituted: true,
          original_name: baseItem.ingredient_name,
        };
      }
      return { ...baseItem, is_substituted: false };
    });
  }, [baseItems]);

  // Group items by phase, preserving insertion order
  const groupByPhase = (items) => {
    const groups = new Map();
    items.forEach(it => {
      const ph = it.phase || "Geral";
      if (!groups.has(ph)) groups.set(ph, []);
      groups.get(ph).push(it);
    });
    return [...groups.entries()];
  };

  const fixedItems = useMemo(() => baseItems.filter(it => !variableSlots.has(it.ingredient_name)), [baseItems, variableSlots]);
  const variableItems = useMemo(() => baseItems.filter(it => variableSlots.has(it.ingredient_name)), [baseItems, variableSlots]);

  return (
    <div className="border rounded-xl bg-background shadow-sm overflow-hidden">
      {/* Collapsed header */}
      <div
        className="flex items-center gap-3 p-4 cursor-pointer hover:bg-muted/30 transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-violet-100 text-violet-600 flex-shrink-0">
          <Combine className="h-4.5 w-4.5" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm truncate">{batch.nome}</p>
          <p className="text-xs text-muted-foreground">
            Base: {baseFormula ? `v${baseFormula.version} — ${baseFormula.name}` : "—"} · <b>{volumeMl} mL</b> por amostra · {variantes.length} variante{variantes.length !== 1 ? "s" : ""}
          </p>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <Badge variant="outline" className={metrics.blocked ? "text-amber-700 border-amber-300" : "text-emerald-700 border-emerald-300"}>
            {metrics.remaining} livre(s)
          </Badge>
          {variantes.map((v, i) => (
            <span key={v.id} className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-violet-50 text-violet-700 border border-violet-200">
              {v.nome || `V${i + 1}`}
            </span>
          ))}
        </div>
        {canEdit && (
          <div className="flex gap-1" onClick={e => e.stopPropagation()}>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button type="button" variant="ghost" size="icon" onClick={() => onEdit(batch)} className="h-7 w-7 text-muted-foreground hover:text-blue-600">
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Editar lote</TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <Button type="button" variant="ghost" size="icon" onClick={() => onDelete(batch.id)} className="h-7 w-7 text-muted-foreground hover:text-red-600">
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? "rotate-180" : ""}`} />
      </div>

      {expanded && (
        <div className="border-t bg-muted/10">
          {baseItems.length === 0 ? (
            <div className="p-6 flex items-center justify-center gap-2 text-muted-foreground text-sm">
              <Loader2 className="h-4 w-4 animate-spin" /> Carregando ingredientes...
            </div>
          ) : (
            <>
              {/* ── Per-variant manipulation orders ── */}
              <div className="p-4 space-y-4">
                <div className="flex items-center gap-2">
                  <FlaskRound className="h-4 w-4 text-violet-600" />
                  <span className="text-xs font-bold uppercase tracking-wider text-violet-700">Ordens de Manipulação</span>
                  <span className="text-[10px] text-muted-foreground">— {volumeMl} mL por amostra (densidade ≈ 1 g/mL)</span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {variantes.map((v, vIdx) => {
                    const resolvedItems = resolveVariantItems(v);
                    const phases = groupByPhase(resolvedItems);
                    const totalPct = resolvedItems.reduce((s, it) => s + (it.percentage || 0), 0);

                    return (
                      <div key={v.id} className="border rounded-lg overflow-hidden shadow-sm">
                        {/* Order header */}
                        <div className="bg-slate-800 dark:bg-slate-900 text-white px-4 py-2.5 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <div className="flex items-center justify-center h-5 w-5 rounded-full bg-violet-400/30 text-[10px] font-bold">{vIdx + 1}</div>
                            <span className="font-bold text-sm">{v.nome || `Variante ${vIdx + 1}`}</span>
                            {v.versao > 1 && <span className="text-[10px] opacity-60">v{v.versao}</span>}
                          </div>
                          <div className="text-[11px] opacity-70 font-mono">{volumeMl} mL</div>
                        </div>

                        {/* Ingredient list by phase */}
                        {phases.map(([phase, items]) => (
                          <div key={phase}>
                            <div className="px-3 py-1 bg-muted/40 border-b border-t text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                              Fase {phase}
                            </div>
                            {items.map((it, itIdx) => (
                              <div
                                key={itIdx}
                                className={`flex items-center justify-between px-3 py-2 border-b text-xs ${
                                  it.is_substituted
                                    ? "bg-amber-50/60 dark:bg-amber-950/20"
                                    : itIdx % 2 === 0 ? "bg-background" : "bg-muted/20"
                                }`}
                              >
                                <div className="flex-1 min-w-0 pr-3">
                                  <span className={`font-medium ${it.is_substituted ? "text-amber-700 dark:text-amber-400" : ""}`}>
                                    {it.ingredient_name}
                                  </span>
                                  {it.is_substituted && (
                                    <span className="ml-1.5 text-[10px] text-amber-600/70 dark:text-amber-500/70">
                                      ↳ subst. {it.original_name}
                                    </span>
                                  )}
                                  {it.fornecedor && (
                                    <span className="ml-1.5 text-[10px] text-muted-foreground">{it.fornecedor}</span>
                                  )}
                                </div>
                                <div className="flex items-center gap-4 flex-shrink-0 text-right">
                                  <span className="text-muted-foreground font-mono w-16">{(it.percentage || 0).toFixed(3)}%</span>
                                  <span className={`font-mono font-bold w-20 ${it.is_substituted ? "text-amber-700 dark:text-amber-400" : ""}`}>
                                    {fmtQty(it.percentage || 0, volumeMl)}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        ))}

                        {/* Order footer */}
                        <div className="flex items-center justify-between px-3 py-2 bg-slate-100 dark:bg-slate-800 font-bold border-t-2">
                          <span className="text-xs">Total</span>
                          <div className="flex items-center gap-4 text-right">
                            <span className="font-mono text-xs text-muted-foreground w-16">{totalPct.toFixed(2)}%</span>
                            <span className="font-mono text-sm w-20">{volumeMl.toFixed(1)} g*</span>
                          </div>
                        </div>

                        {v.notas && (
                          <div className="px-3 py-1.5 text-[10px] text-muted-foreground bg-muted/20 border-t italic">{v.notas}</div>
                        )}
                      </div>
                    );
                  })}
                </div>

                <p className="text-[10px] text-muted-foreground">* Estimativa assumindo densidade ≈ 1,0 g/mL (produto aquoso). Ajuste conforme densidade real do produto.</p>
              </div>

              {/* ── Comparativo (collapsible) ── */}
              <div className="border-t">
                <button
                  onClick={() => setShowComparativo(s => !s)}
                  className="w-full flex items-center gap-2 px-4 py-2.5 text-xs text-muted-foreground hover:bg-muted/20 transition-colors"
                >
                  <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showComparativo ? "rotate-180" : ""}`} />
                  Tabela comparativa de variantes
                </button>
                {showComparativo && (
                  <div className="border-t overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-muted/50">
                          <th className="p-2 text-left font-medium text-muted-foreground">Ingrediente</th>
                          <th className="p-2 text-right font-medium text-muted-foreground">% Base</th>
                          <th className="p-2 text-right font-medium text-muted-foreground">g/{volumeMl}mL</th>
                          {variantes.map(v => (
                            <th key={v.id} className="p-2 text-center font-medium text-violet-700 bg-violet-50/60">
                              {v.nome || "Variante"}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {fixedItems.map(it => (
                          <tr key={it.id} className="border-t hover:bg-muted/20">
                            <td className="p-2 font-medium">{it.ingredient_name}</td>
                            <td className="p-2 text-right font-mono">{(it.percentage || 0).toFixed(3)}</td>
                            <td className="p-2 text-right font-mono">{fmtQty(it.percentage || 0, volumeMl)}</td>
                            {variantes.map(v => (
                              <td key={v.id} className="p-2 text-center text-muted-foreground bg-violet-50/30">—</td>
                            ))}
                          </tr>
                        ))}
                        {variableItems.map(it => (
                          <tr key={it.id} className="border-t bg-amber-50/40 hover:bg-amber-50/60">
                            <td className="p-2 font-medium text-amber-700">{it.ingredient_name} <span className="text-[10px] bg-amber-100 text-amber-600 rounded px-1 ml-1">variável</span></td>
                            <td className="p-2 text-right font-mono text-amber-700">{(it.percentage || 0).toFixed(3)}</td>
                            <td className="p-2 text-right font-mono text-amber-700">{fmtQty(it.percentage || 0, volumeMl)}</td>
                            {variantes.map(v => {
                              const ov = (v.overrides || []).find(o => o.ingredient_name_base === it.ingredient_name);
                              return (
                                <td key={v.id} className="p-2 text-center bg-violet-50/50">
                                  {ov ? (
                                    <div>
                                      <p className="font-medium text-violet-700">{ov.ingredient_name || it.ingredient_name}</p>
                                      <p className="font-mono text-violet-600">{(ov.percentage || 0).toFixed(3)}%</p>
                                      <p className="font-mono text-[10px] text-violet-500">{fmtQty(ov.percentage || 0, volumeMl)}</p>
                                      {ov.fornecedor && <p className="text-[10px] text-muted-foreground">{ov.fornecedor}</p>}
                                    </div>
                                  ) : (
                                    <span className="text-muted-foreground">base</span>
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr className="border-t-2 bg-muted/30 font-bold">
                          <td className="p-2 text-xs">Total</td>
                          <td className="p-2 text-right font-mono">{baseItems.reduce((s, it) => s + (it.percentage || 0), 0).toFixed(2)}</td>
                          <td className="p-2 text-right font-mono">{volumeMl.toFixed(0)} mL</td>
                          {variantes.map(v => <td key={v.id} className="p-2 bg-violet-50/30" />)}
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                )}
              </div>

              {batch.notas && (
                <div className="px-4 py-2 border-t">
                  <p className="text-xs text-muted-foreground bg-muted/30 rounded p-2">{batch.notas}</p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function SampleBatchSection({ devId, formulas, onRefresh, canEdit }) {
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingBatch, setEditingBatch] = useState(null);

  const fetchBatches = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/pd/developments/${devId}/sample-batches`);
      setBatches(Array.isArray(data) ? data : []);
    } catch { setBatches([]); } finally { setLoading(false); }
  }, [devId]);

  useEffect(() => { fetchBatches(); }, [fetchBatches]);

  const handleSave = async (form) => {
    if (editingBatch) {
      await api.put(`/pd/developments/${devId}/sample-batches/${editingBatch.id}`, form);
      toast.success("Lote atualizado");
    } else {
      await api.post(`/pd/developments/${devId}/sample-batches`, form);
      toast.success("Lote criado");
    }
    await fetchBatches();
  };

  const handleDelete = async (batchId) => {
    if (!window.confirm("Remover este lote de amostras?")) return;
    try {
      await api.delete(`/pd/developments/${devId}/sample-batches/${batchId}`);
      toast.success("Lote removido");
      fetchBatches();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao remover lote"); }
  };

  const openCreate = () => { setEditingBatch(null); setEditorOpen(true); };
  const openEdit = (batch) => { setEditingBatch(batch); setEditorOpen(true); };

  return (
    <div className="mt-8 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-px flex-1 bg-border" />
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-violet-50 border border-violet-200">
            <GitBranch className="h-3.5 w-3.5 text-violet-600" />
            <span className="text-xs font-semibold text-violet-700">Lotes de Amostras</span>
            {batches.length > 0 && (
              <span className="text-[10px] bg-violet-200 text-violet-700 rounded-full px-1.5">{batches.length}</span>
            )}
          </div>
          <div className="h-px flex-1 bg-border" />
        </div>
        {canEdit && formulas.length > 0 && (
          <Button variant="outline" size="sm" onClick={openCreate} className="ml-3 h-7 text-xs gap-1 border-violet-200 text-violet-700 hover:bg-violet-50">
            <Plus className="h-3 w-3" />Novo Lote
          </Button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : batches.length === 0 ? (
        <div className="text-center py-8 border border-dashed rounded-xl bg-muted/20">
          <Combine className="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">Nenhum lote de amostras ainda.</p>
          {canEdit && formulas.length > 0 && (
            <p className="text-xs text-muted-foreground mt-1">Crie um lote para organizar variantes com mesma base (ex: diferentes fragrâncias).</p>
          )}
          {formulas.length === 0 && (
            <p className="text-xs text-muted-foreground mt-1">Crie uma fórmula base primeiro para habilitar lotes.</p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {batches.map(batch => (
            <SampleBatchCard
              key={batch.id}
              batch={batch}
              formulas={formulas}
              onEdit={openEdit}
              onDelete={handleDelete}
              canEdit={canEdit}
            />
          ))}
        </div>
      )}

      <Dialog open={editorOpen} onOpenChange={open => { if (!open) setEditorOpen(false); }}>
        <DialogContent className="w-[calc(100vw-2rem)] max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <GitBranch className="h-5 w-5 text-violet-600" />
              {editingBatch ? "Editar Lote de Amostras" : "Novo Lote de Amostras"}
            </DialogTitle>
            <DialogDescription>
              Defina uma fórmula base e configure variantes com substituições de ingredientes (ex: fragrâncias diferentes).
            </DialogDescription>
          </DialogHeader>
          {editorOpen && (
            <SampleBatchEditor
              devId={devId}
              formulas={formulas}
              initial={editingBatch}
              onSave={handleSave}
              onClose={() => setEditorOpen(false)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ============ STABILITY GRID PANEL (shared between Estabilidades + Testes) ============ */

// STABILITY_CONDITIONS (backend/pd_routes.py) hoje só emite 5 códigos para estudos NOVOS
// (ambient/oven_45/freezer_minus5/light_exposure/freeze_thaw). Os 4 extras abaixo
// (climate_30_75/oven_40/refrigerated_5/dark_storage) foram removidos do backend no
// commit b145deb, mas estudos criados antes dele ainda têm esses códigos gravados em
// db.pd_stability_studies — mantidos aqui só para essas leituras antigas continuarem
// com ícone/cor próprios no histórico (read-only). Não oferecidos em estudos novos.
const CONDITION_ICONS = {
  ambient: Sparkles,
  climate_30_75: Wind,
  oven_40: Thermometer,
  oven_45: Thermometer,
  refrigerated_5: Snowflake,
  freezer_minus5: Snowflake,
  light_exposure: Sun,
  dark_storage: Eye,
  freeze_thaw: RefreshCw,
};

const CONDITION_COLORS = {
  ambient: "text-green-600",
  climate_30_75: "text-yellow-600",
  oven_40: "text-orange-500",
  oven_45: "text-red-500",
  refrigerated_5: "text-blue-400",
  freezer_minus5: "text-blue-600",
  light_exposure: "text-yellow-500",
  dark_storage: "text-purple-500",
  freeze_thaw: "text-cyan-500",
};

const fmtDay = (d) => d === 1 ? "D24h" : d === 2 ? "D48h" : `D${d}`;

// R12: painel compartilhado — mesma fonte de dados para Testes e Estabilidades
function StabilityGridPanel({ reqId, canEdit, onReadingsLoaded, showStudyHeader = true }) {
  const [study, setStudy] = useState(null);
  const [readings, setReadings] = useState([]);
  const [constants, setConstants] = useState({ conditions: [], parameters: [], checkpoints: [] });
  const [loading, setLoading] = useState(true);
  const [readingDialog, setReadingDialog] = useState(null);
  const [readingForm, setReadingForm] = useState({ day_offset: 0, parameters: {}, notes: "" });
  const [savingReading, setSavingReading] = useState(false);

  const fetchStudy = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/pd/requests/${reqId}/stability-study`);
      setStudy(data.study);
      const rs = data.readings || [];
      const cs = data.constants || { conditions: [], parameters: [], checkpoints: [] };
      setReadings(rs);
      setConstants(cs);
      // Notifica o parent sobre leituras (R13)
      onReadingsLoaded?.(rs, cs.conditions || []);
    } catch (err) {
      toast.error("Erro ao carregar estabilidades");
    } finally { setLoading(false); }
  }, [reqId, onReadingsLoaded]);

  useEffect(() => { fetchStudy(); }, [fetchStudy]);

  const readingsByCondition = useMemo(() => {
    const map = {};
    readings.forEach(r => {
      if (!map[r.condition_code]) map[r.condition_code] = {};
      map[r.condition_code][r.day_offset] = r;
    });
    return map;
  }, [readings]);

  const openReadingDialog = (cond) => {
    const existing = readingsByCondition[cond.code] || {};
    const completed = Object.keys(existing).map(Number);
    const condCps = study?.conditions?.find(c => c.code === cond.code)?.checkpoints ?? cond.checkpoints ?? constants.checkpoints;
    const pending = condCps.filter(d => !completed.includes(d));
    const nextDay = pending[0] ?? condCps[0] ?? 1;
    setReadingForm({ day_offset: nextDay, parameters: {}, notes: "" });
    setReadingDialog(cond);
  };

  const submitReading = async () => {
    if (!readingDialog || !study) return;
    if (Object.keys(readingForm.parameters).length === 0) return toast.error("Informe ao menos um parâmetro");
    setSavingReading(true);
    try {
      await api.post(`/pd/stability/studies/${study.id}/readings`, {
        condition_code: readingDialog.code,
        day_offset: readingForm.day_offset,
        parameters: readingForm.parameters,
        notes: readingForm.notes,
      });
      toast.success(`Leitura ${fmtDay(readingForm.day_offset)} registrada!`);
      setReadingDialog(null);
      fetchStudy();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao registrar leitura");
    } finally { setSavingReading(false); }
  };

  const getOverallStatus = (cond) => {
    const studyCond = study?.conditions?.find(c => c.code === cond.code);
    return studyCond?.status || "pending";
  };

  const isAlertD2 = (cond) => {
    const studyCond = study?.conditions?.find(c => c.code === cond.code);
    if (!studyCond?.next_due_at) return false;
    const diff = new Date(studyCond.next_due_at).getTime() - Date.now();
    return diff > 0 && diff <= 2 * 24 * 3600 * 1000;
  };

  if (loading) return <div className="flex items-center justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;

  const defaultCheckpointLabel = (constants.checkpoints || []).map(fmtDay).join(" / ");
  const freezeThawCheckpointLabel = (
    constants.conditions.find(cond => cond.code === "freeze_thaw")?.checkpoints || []
  ).map(fmtDay).join(" / ");

  return (
    <div className="space-y-5" data-testid="stability-grid-panel">
      {/* Study Header — opcional */}
      {showStudyHeader && study && (
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold flex items-center gap-2">
              <TestTube className="h-4 w-4 text-primary" />
              Estudo de Estabilidade
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Iniciado: {study.started_at ? new Date(study.started_at).toLocaleDateString("pt-BR") : "—"}
              &nbsp;·&nbsp;Checkpoints: {constants.checkpoints.map(fmtDay).join(" / ")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={study.status === "concluido" ? "default" : "secondary"} className="text-xs">
              {study.status === "concluido" ? "Concluído" : study.status === "ativo" ? "Ativo" : study.status}
            </Badge>
            <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={fetchStudy}>
              <RefreshCw className="h-3 w-3" /> Atualizar
            </Button>
          </div>
        </div>
      )}

      {freezeThawCheckpointLabel && (
        <p className="text-[11px] text-muted-foreground">
          Base: {defaultCheckpointLabel}. Freeze/Thaw segue checkpoints proprios: {freezeThawCheckpointLabel}.
        </p>
      )}

      {/* Conditions Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {constants.conditions.map(cond => {
          const CIcon = CONDITION_ICONS[cond.code] || Thermometer;
          const colorCls = CONDITION_COLORS[cond.code] || "text-muted-foreground";
          const existing = readingsByCondition[cond.code] || {};
          const studyCond = study?.conditions?.find(c => c.code === cond.code);
          const condCheckpoints = studyCond?.checkpoints ?? cond.checkpoints ?? constants.checkpoints;
          const completedDays = Object.keys(existing).map(Number).sort((a, b) => a - b);
          const total = condCheckpoints.length;
          const done = completedDays.length;
          const progress = total > 0 ? (done / total) * 100 : 0;
          const status = getOverallStatus(cond);
          const alertD2 = isAlertD2(cond);
          const nextDue = studyCond?.next_due_day_offset;
          return (
            <Card key={cond.code} className={`relative ${alertD2 ? "border-amber-400 shadow-amber-100" : ""}`} data-testid={`condition-${cond.code}`}>
              {alertD2 && (
                <div className="absolute top-2 right-2">
                  <Badge className="text-[10px] bg-amber-500 text-white animate-pulse">D+2</Badge>
                </div>
              )}
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <CIcon className={`h-4 w-4 ${colorCls}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{cond.label}</p>
                    <p className="text-[11px] text-muted-foreground">{cond.temperature} · {cond.humidity}</p>
                  </div>
                </div>
                {/* Progress bar */}
                <div>
                  <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
                    <span>{done}/{total} checkpoints</span>
                    {nextDue != null && <span className="text-blue-600">Próx: {fmtDay(nextDue)}</span>}
                  </div>
                  <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-primary transition-all rounded-full" style={{ width: `${progress}%` }} />
                  </div>
                </div>
                {/* Checkpoints chips */}
                <div className="flex flex-wrap gap-1">
                  {condCheckpoints.map(day => {
                    const reading = existing[day];
                    return (
                      <span
                        key={day}
                        className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium border ${
                          reading ? "bg-green-50 border-green-300 text-green-700" : "bg-muted border-border text-muted-foreground"
                        }`}
                        title={reading ? `Registrado em ${new Date(reading.reading_at).toLocaleDateString("pt-BR")}` : `${fmtDay(day)} pendente`}
                      >
                        {fmtDay(day)}{reading ? " ✓" : ""}
                      </span>
                    );
                  })}
                </div>
                {canEdit && study?.status !== "concluido" && (
                  <Button size="sm" variant="outline" className="w-full h-7 text-xs gap-1" onClick={() => openReadingDialog(cond)} data-testid={`registrar-leitura-${cond.code}`}>
                    <Plus className="h-3 w-3" /> Registrar Leitura
                  </Button>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Registrar Leitura Dialog */}
      {readingDialog && (
        <Dialog open onOpenChange={() => setReadingDialog(null)}>
          <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <TestTube className="h-4 w-4 text-primary" />
                Registrar Leitura — {readingDialog.label}
              </DialogTitle>
              <DialogDescription>
                {readingDialog.temperature} · {readingDialog.humidity}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div>
                <Label className="text-sm font-medium">Checkpoint (Dia)</Label>
                <Select value={String(readingForm.day_offset)} onValueChange={v => setReadingForm(p => ({ ...p, day_offset: Number(v) }))}>
                  <SelectTrigger className="mt-1" data-testid="checkpoint-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(study?.conditions?.find(c => c.code === readingDialog.code)?.checkpoints ?? readingDialog.checkpoints ?? constants.checkpoints).map(d => {
                      const alreadyDone = !!(readingsByCondition[readingDialog.code] || {})[d];
                      return (
                        <SelectItem key={d} value={String(d)} disabled={alreadyDone}>
                          {fmtDay(d)} {alreadyDone ? "(já registrado)" : ""}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {constants.parameters.map(param => (
                  <div key={param.code}>
                    <Label className="text-xs text-muted-foreground">{param.label}</Label>
                    <Input
                      value={readingForm.parameters[param.code] || ""}
                      onChange={e => setReadingForm(p => ({ ...p, parameters: { ...p.parameters, [param.code]: e.target.value } }))}
                      placeholder={param.label}
                      className="h-8 text-sm mt-1"
                      data-testid={`param-${param.code}`}
                    />
                  </div>
                ))}
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">Observações</Label>
                <Textarea value={readingForm.notes} onChange={e => setReadingForm(p => ({ ...p, notes: e.target.value }))} placeholder="Observações adicionais..." rows={2} className="mt-1" />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setReadingDialog(null)}>Cancelar</Button>
              <Button onClick={submitReading} disabled={savingReading} data-testid="submit-reading-btn">
                {savingReading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Save className="h-4 w-4 mr-2" />}
                Salvar Leitura {fmtDay(readingForm.day_offset)}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

// R12: wrapper fino — mantém aba "Estabilidades" inalterada externamente
/* ============ FICHA TÉCNICA TAB ============ */
const FT_PARAMS = [
  { key: "aspecto", label: "Aspecto" },
  { key: "cor", label: "Cor" },
  { key: "densidade", label: "Densidade" },
  { key: "odor", label: "Odor" },
  { key: "ph", label: "pH" },
  { key: "teor_alcool", label: "Teor de Álcool" },
];

const EMPTY_ELABORACAO = { secoes: [] };

function FichaTecnicaTab({ reqId, formulas, req, dev, canEdit, labResults }) {
  // Garante shape completo por seção — dados legados podem ter sido gravados sem `etapas`
  // (ou por um caller futuro que não espelhe addSecao), o que quebrava o render em .map().
  const normalizeSecao = useCallback((secao, idx) => ({
    id: secao?.id || `s${idx}`,
    nome: secao?.nome || `Fase ${indexToLetters(idx)}`,
    tipo: secao?.tipo || "",
    temperatura: secao?.temperatura || "",
    agitacao: secao?.agitacao || "",
    tempo_min: secao?.tempo_min || "",
    etapas: Array.isArray(secao?.etapas) ? secao.etapas : (secao?.etapas ? [String(secao.etapas)] : [""]),
  }), []);
  const parseElaboracao = useCallback((raw) => {
    if (!raw) return EMPTY_ELABORACAO;
    if (typeof raw === "object" && Array.isArray(raw.secoes)) {
      return { ...raw, secoes: raw.secoes.map(normalizeSecao) };
    }
    // legacy plain string → migrate to single section
    if (typeof raw === "string" && raw.trim()) return { secoes: [{ id: "s1", nome: "Modo de Preparo", temperatura: "", etapas: [raw] }] };
    return EMPTY_ELABORACAO;
  }, [normalizeSecao]);
  // Dados legados podem ter aspecto/cor/densidade/... gravados como string simples
  // (versão anterior da ficha). O backend exige objeto {especificacao, resultado, pa} —
  // sem essa normalização, salvar reenvia a string e o backend rejeita com 422.
  const normalizeParam = useCallback((val) => {
    if (val && typeof val === "object") return { especificacao: val.especificacao || "", resultado: val.resultado || "", pa: val.pa || "" };
    if (typeof val === "string" && val.trim()) return { especificacao: "", resultado: val, pa: "" };
    return { especificacao: "", resultado: "", pa: "" };
  }, []);
  const [autoFilled, setAutoFilled] = useState({});

  const [form, setForm] = useState({
    produto: "", lote: "", data_fabricacao: "", validade: "", quantidade: "",
    elaboracao: EMPTY_ELABORACAO, resp_tecnico: "", status_aprovacao: "",
    aspecto: { especificacao: "", resultado: "", pa: "" },
    cor: { especificacao: "", resultado: "", pa: "" },
    densidade: { especificacao: "", resultado: "", pa: "" },
    odor: { especificacao: "", resultado: "", pa: "" },
    ph: { especificacao: "", resultado: "", pa: "" },
    teor_alcool: { especificacao: "", resultado: "", pa: "" },
  });
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get(`/pd/requests/${reqId}/ficha-tecnica-ui`).then(({ data }) => {
      const a = data.analise || {};
      const fallbackLabResults = data.lab_results && Object.keys(data.lab_results).length > 0 ? data.lab_results : (labResults || {});
      const fallbackAutoFilled = data.auto_filled || {
        aspecto: !normalizeParam(a.aspecto).resultado && !!fallbackLabResults?.sensorial?.aspecto,
        cor: !normalizeParam(a.cor).resultado && !!fallbackLabResults?.sensorial?.cor,
        odor: !normalizeParam(a.odor).resultado && !!fallbackLabResults?.sensorial?.odor,
        ph: !normalizeParam(a.ph).resultado && !!fallbackLabResults?.ph?.valor_medido,
      };
      setAutoFilled(fallbackAutoFilled);
      setForm({
        produto: a.produto || req.project_name || "",
        lote: a.lote || "",
        data_fabricacao: a.data_fabricacao || "",
        validade: a.validade || "",
        quantidade: a.quantidade || "",
        elaboracao: parseElaboracao(a.elaboracao),
        resp_tecnico: a.resp_tecnico || "",
        status_aprovacao: a.status_aprovacao || "",
        aspecto: normalizeParam(a.aspecto),
        cor: normalizeParam(a.cor),
        densidade: normalizeParam(a.densidade),
        odor: normalizeParam(a.odor),
        ph: normalizeParam(a.ph),
        teor_alcool: normalizeParam(a.teor_alcool),
      });
    }).catch(() => {}).finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reqId, req.project_name, labResults, parseElaboracao, normalizeParam]);

  const setParam = (key, field, val) => {
    setForm(prev => ({ ...prev, [key]: { ...prev[key], [field]: val } }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.put(`/pd/requests/${reqId}/ficha-tecnica-ui`, form);
      toast.success("Ficha Técnica salva!");
    } catch (err) {
      // FastAPI retorna `detail` como array de objetos em erros 422 — passar isso direto
      // ao toast quebra o render (React não aceita array de objetos como child) e derruba a tela.
      toast.error(formatApiError(err) || "Erro ao salvar");
    } finally { setSaving(false); }
  };

  const elab = form.elaboracao || { secoes: [], observacoes_gerais: "" };
  const setElab = (updater) => setForm(p => ({ ...p, elaboracao: updater(p.elaboracao || { secoes: [], observacoes_gerais: "" }) }));

  const addSecao = () => setElab(e => ({
    ...e,
    secoes: [...e.secoes, {
      id: `s${Date.now()}`,
      nome: `Fase ${indexToLetters(e.secoes.length)}`,
      tipo: "",
      temperatura: "",
      agitacao: "",
      tempo_min: "",
      etapas: [""],
    }]
  }));
  const removeSecao = (sid) => setElab(e => ({ ...e, secoes: e.secoes.filter(s => s.id !== sid) }));
  const updateSecao = (sid, field, val) => setElab(e => ({ ...e, secoes: e.secoes.map(s => s.id === sid ? { ...s, [field]: val } : s) }));
  const addEtapa = (sid) => setElab(e => ({ ...e, secoes: e.secoes.map(s => s.id === sid ? { ...s, etapas: [...(s.etapas || []), ""] } : s) }));
  const removeEtapa = (sid, idx) => setElab(e => ({ ...e, secoes: e.secoes.map(s => s.id === sid ? { ...s, etapas: (s.etapas || []).filter((_, i) => i !== idx) } : s) }));
  const updateEtapa = (sid, idx, val) => setElab(e => ({ ...e, secoes: e.secoes.map(s => s.id === sid ? { ...s, etapas: (s.etapas || []).map((et, i) => i === idx ? val : et) } : s) }));
  const moveSecao = (idx, dir) => setElab(e => {
    const arr = [...e.secoes];
    const to = idx + dir;
    if (to < 0 || to >= arr.length) return e;
    [arr[idx], arr[to]] = [arr[to], arr[idx]];
    return { ...e, secoes: arr };
  });

  const latest = formulas?.[0];
  const items = latest?.items || [];

  if (loading) return <div className="flex items-center justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;

  return (
    <div className="space-y-6 max-w-4xl" data-testid="ficha-tecnica-tab">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-primary" />
            Ficha Técnica de Manipulação
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">Laudo analítico do produto fabricado</p>
        </div>
        {canEdit && (
          <Button size="sm" onClick={handleSave} disabled={saving} className="gap-1.5" data-testid="ft-save-btn">
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            Salvar Ficha
          </Button>
        )}
      </div>

      {/* Identificação */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Identificação do Produto</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {[
            { key: "produto", label: "Produto" },
            { key: "lote", label: "Lote" },
            { key: "data_fabricacao", label: "Data de Fabricação" },
            { key: "validade", label: "Validade" },
            { key: "quantidade", label: "Quantidade" },
          ].map(({ key, label }) => (
            <div key={key}>
              <Label className="text-xs text-muted-foreground">{label}</Label>
              <Input
                value={form[key] || ""}
                onChange={e => setForm(p => ({ ...p, [key]: e.target.value }))}
                placeholder={label}
                className="h-8 text-sm mt-1"
                disabled={!canEdit}
                data-testid={`ft-field-${key}`}
              />
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Tabela de Análise do Produto Fabricado */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Análise do Produto Fabricado</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="border rounded-b-md overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-[#0A0A0B] text-white text-xs">
                  <th className="text-left p-3 font-medium w-32">TESTE</th>
                  <th className="text-left p-3 font-medium">ESPECIFICAÇÃO</th>
                  <th className="text-left p-3 font-medium">RESULTADO</th>
                  <th className="text-center p-3 font-medium w-36">PA</th>
                </tr>
              </thead>
              <tbody>
                {FT_PARAMS.map(({ key, label }) => (
                  <tr key={key} className="border-t hover:bg-muted/20">
                    <td className="p-3 font-medium text-sm">
                      {label}
                      {autoFilled[key] && (
                        <span className="ml-1.5 text-[9px] font-normal text-emerald-600" title="Preenchido a partir de Características Padrão (aba Testes)">
                          (de Características Padrão)
                        </span>
                      )}
                    </td>
                    <td className="p-2">
                      <Input
                        value={form[key]?.especificacao || ""}
                        onChange={e => setParam(key, "especificacao", e.target.value)}
                        placeholder="Especificação..."
                        className="h-7 text-xs border-0 bg-transparent focus:bg-background focus:border"
                        disabled={!canEdit}
                        data-testid={`ft-${key}-especificacao`}
                      />
                    </td>
                    <td className="p-2">
                      <Input
                        value={form[key]?.resultado || ""}
                        onChange={e => { setAutoFilled(prev => ({ ...prev, [key]: false })); setParam(key, "resultado", e.target.value); }}
                        placeholder="Resultado medido..."
                        className="h-7 text-xs border-0 bg-transparent focus:bg-background focus:border"
                        disabled={!canEdit}
                        data-testid={`ft-${key}-resultado`}
                      />
                    </td>
                    <td className="p-2 text-center">
                      {canEdit ? (
                        <Select value={form[key]?.pa || ""} onValueChange={v => setParam(key, "pa", v)}>
                          <SelectTrigger className="h-7 text-xs w-full" data-testid={`ft-${key}-pa`}>
                            <SelectValue placeholder="—" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="Conforme">Conforme</SelectItem>
                            <SelectItem value="Não Conforme">Não Conforme</SelectItem>
                            <SelectItem value="N/A">N/A</SelectItem>
                          </SelectContent>
                        </Select>
                      ) : (
                        <Badge className={
                          form[key]?.pa === "Conforme" ? "bg-green-500/20 text-green-700 border-green-300" :
                          form[key]?.pa === "Não Conforme" ? "bg-red-500/20 text-red-700 border-red-300" :
                          "bg-muted text-muted-foreground"
                        }>
                          {form[key]?.pa || "—"}
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Tabela de Formulação */}
      {items.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground flex items-center justify-between">
              Formulação
              {latest && <Badge variant="outline" className="font-mono text-xs">v{latest.version}</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-hidden border-t">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-muted text-muted-foreground">
                    <th className="text-left p-2 font-medium">Ingrediente</th>
                    <th className="text-left p-2 font-medium">Fornecedor</th>
                    <th className="text-right p-2 font-medium w-20">%Fórmula</th>
                    <th className="text-right p-2 font-medium w-24">Qtd/Lote</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, i) => {
                    const vol = latest?.volume || 0;
                    const vu = latest?.volume_unit || "mL";
                    const qty = vol > 0 ? `${(vol * (item.percentage || 0) / 100).toFixed(3)} ${vu}` : "—";
                    return (
                      <tr key={item.id || i} className="border-t hover:bg-muted/20">
                        <td className="p-2 font-medium">{item.ingredient_name}</td>
                        <td className="p-2 text-muted-foreground">{item.fornecedor || "—"}</td>
                        <td className="p-2 text-right font-mono">{(item.percentage || 0).toFixed(3)}</td>
                        <td className="p-2 text-right font-mono text-blue-600">{qty}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Descrição da Elaboração — Modo de Preparo (padrão Ameratti) */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                2.2 · Descrição da Elaboração — Modo de Preparo
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                Fase a fase · etapa a etapa · ingredientes vinculados da fórmula
              </p>
            </div>
            {canEdit && (
              <Button size="sm" variant="outline" className="h-7 gap-1 text-xs shrink-0" onClick={addSecao}>
                <Plus className="h-3 w-3" /> Adicionar Fase
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4 pt-2" data-testid="ft-elaboracao">
          {elab.secoes.length === 0 && (
            <div className="text-center py-10 text-muted-foreground border-2 border-dashed rounded-xl">
              <p className="text-sm font-medium">Nenhuma fase adicionada</p>
              {canEdit && <p className="text-xs mt-1">Use "+ Adicionar Fase" para criar Fase A, B, C...</p>}
            </div>
          )}

          {elab.secoes.map((secao, sIdx) => {
            // Auto-link formula items whose "phase" field matches this section name (case-insensitive)
            const linkedItems = (items || []).filter(it =>
              it.phase && secao.nome &&
              it.phase.trim().toLowerCase() === secao.nome.trim().toLowerCase()
            );
            const vol = latest?.volume || 0;
            const vu = latest?.volume_unit || "mL";

            const TIPO_COLORS = {
              "Aquosa":        "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30",
              "Oleosa":        "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30",
              "Conservantes":  "bg-violet-500/15 text-violet-700 dark:text-violet-300 border-violet-500/30",
              "Ativos":        "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
              "Emulsificação": "bg-orange-500/15 text-orange-700 dark:text-orange-300 border-orange-500/30",
              "Resfriamento":  "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 border-cyan-500/30",
              "Ajuste de pH":  "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30",
              "Outro":         "bg-slate-500/15 text-slate-600 dark:text-slate-300 border-slate-500/30",
            };
            const tipoColor = TIPO_COLORS[secao.tipo] || "";

            return (
              <div key={secao.id} className="border rounded-xl overflow-hidden shadow-sm">
                {/* ── Phase header ── */}
                <div className="bg-[#0A0A0B] text-white px-4 py-2.5 flex items-center gap-3 flex-wrap">
                  {/* Letter badge */}
                  <span className="flex items-center justify-center h-7 w-7 rounded-lg bg-white/10 text-sm font-bold shrink-0">
                    {indexToLetters(sIdx)}
                  </span>

                  {/* Phase name */}
                  {canEdit ? (
                    <Input
                      value={secao.nome}
                      onChange={e => updateSecao(secao.id, "nome", e.target.value)}
                      className="h-7 w-36 text-sm font-semibold bg-transparent border-0 border-b border-white/30 rounded-none text-white placeholder:text-white/40 focus:border-white/70 px-0"
                      placeholder="Nome da fase..."
                    />
                  ) : (
                    <span className="text-sm font-semibold">{secao.nome}</span>
                  )}

                  {/* Tipo */}
                  {canEdit ? (
                    <select
                      value={secao.tipo || ""}
                      onChange={e => updateSecao(secao.id, "tipo", e.target.value)}
                      className="h-7 text-xs bg-white/10 border border-white/20 rounded px-2 text-white focus:outline-none focus:border-white/50"
                    >
                      <option value="">Tipo...</option>
                      {["Aquosa","Oleosa","Conservantes","Ativos","Emulsificação","Resfriamento","Ajuste de pH","Outro"].map(t => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                  ) : secao.tipo ? (
                    <span className={`text-[11px] font-medium border rounded-full px-2.5 py-0.5 ${tipoColor}`}>{secao.tipo}</span>
                  ) : null}

                  {/* Temperatura */}
                  {canEdit ? (
                    <div className="flex items-center gap-1">
                      <Thermometer className="h-3.5 w-3.5 text-white/50 shrink-0" />
                      <Input
                        value={secao.temperatura || ""}
                        onChange={e => updateSecao(secao.id, "temperatura", e.target.value)}
                        className="h-6 w-20 text-xs bg-transparent border-0 border-b border-white/30 rounded-none text-white placeholder:text-white/40 focus:border-white/70 px-0"
                        placeholder="ex: 70°C"
                      />
                    </div>
                  ) : secao.temperatura ? (
                    <span className="flex items-center gap-1 text-white/70 text-xs">
                      <Thermometer className="h-3 w-3" />{secao.temperatura}
                    </span>
                  ) : null}

                  {/* Agitação */}
                  {canEdit ? (
                    <select
                      value={secao.agitacao || ""}
                      onChange={e => updateSecao(secao.id, "agitacao", e.target.value)}
                      className="h-7 text-xs bg-white/10 border border-white/20 rounded px-2 text-white focus:outline-none focus:border-white/50"
                    >
                      <option value="">Agitação...</option>
                      {["Suave","Média","Alta","Homogeneizador","Sem agitação"].map(a => (
                        <option key={a} value={a}>{a}</option>
                      ))}
                    </select>
                  ) : secao.agitacao ? (
                    <span className="text-white/60 text-xs">Agit. {secao.agitacao}</span>
                  ) : null}

                  {/* Tempo */}
                  {canEdit ? (
                    <div className="flex items-center gap-1">
                      <span className="text-white/50 text-xs">Tempo:</span>
                      <Input
                        value={secao.tempo_min || ""}
                        onChange={e => updateSecao(secao.id, "tempo_min", e.target.value)}
                        className="h-6 w-14 text-xs bg-transparent border-0 border-b border-white/30 rounded-none text-white placeholder:text-white/40 focus:border-white/70 px-0"
                        placeholder="min"
                      />
                    </div>
                  ) : secao.tempo_min ? (
                    <span className="text-white/60 text-xs">{secao.tempo_min} min</span>
                  ) : null}

                  {/* Controls */}
                  <div className="ml-auto flex items-center gap-1 shrink-0">
                    {canEdit && (
                      <>
                        <button type="button" onClick={() => moveSecao(sIdx, -1)} disabled={sIdx === 0}
                          className="h-6 w-6 flex items-center justify-center rounded hover:bg-white/10 disabled:opacity-30 text-white/70">
                          <ChevronUp className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" onClick={() => moveSecao(sIdx, 1)} disabled={sIdx === elab.secoes.length - 1}
                          className="h-6 w-6 flex items-center justify-center rounded hover:bg-white/10 disabled:opacity-30 text-white/70">
                          <ChevronDown className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" onClick={() => removeSecao(secao.id)}
                          className="h-6 w-6 flex items-center justify-center rounded hover:bg-red-500/30 text-white/60 hover:text-red-300 ml-1">
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* ── Linked ingredients (auto from formula) ── */}
                {linkedItems.length > 0 && (
                  <div className="border-b bg-muted/20">
                    <div className="px-4 py-1.5 flex items-center gap-2">
                      <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        Ingredientes desta fase (da fórmula)
                      </span>
                      <span className="text-[10px] text-muted-foreground border rounded-full px-1.5 py-px">{linkedItems.length}</span>
                    </div>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-t border-b text-muted-foreground">
                          <th className="text-left px-4 py-1.5 font-medium">Ingrediente</th>
                          <th className="text-left px-3 py-1.5 font-medium">Fornecedor</th>
                          <th className="text-right px-3 py-1.5 font-medium w-20">% Fórmula</th>
                          <th className="text-right px-4 py-1.5 font-medium w-24">Qtd / Lote</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {linkedItems.map(item => {
                          const qty = vol > 0 ? `${(vol * (item.percentage || 0) / 100).toFixed(3)} ${vu}` : "—";
                          return (
                            <tr key={item.id} className="hover:bg-muted/30">
                              <td className="px-4 py-1.5 font-medium">{item.ingredient_name}</td>
                              <td className="px-3 py-1.5 text-muted-foreground">{item.fornecedor || "—"}</td>
                              <td className="px-3 py-1.5 text-right font-mono">{(item.percentage || 0).toFixed(3)}</td>
                              <td className="px-4 py-1.5 text-right font-mono text-blue-600 dark:text-blue-400">{qty}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                {linkedItems.length === 0 && items.length > 0 && (
                  <div className="border-b bg-muted/10 px-4 py-2 flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground/60 italic">
                      Nenhum ingrediente da fórmula com fase "{secao.nome}".
                      Defina o campo "Fase" nos ingredientes da formulação para vincular aqui.
                    </span>
                  </div>
                )}

                {/* ── Procedimento / Steps ── */}
                <div className="divide-y">
                  <div className="px-4 py-1.5 bg-muted/10">
                    <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Procedimento</span>
                  </div>
                  {(secao.etapas || []).map((etapa, eIdx) => (
                    <div key={eIdx} className="flex items-start gap-2 px-4 py-2 hover:bg-muted/20 group">
                      <span className="text-xs font-mono font-bold text-muted-foreground/60 mt-2 w-5 shrink-0 text-right select-none">
                        {eIdx + 1}.
                      </span>
                      {canEdit ? (
                        <Textarea
                          value={etapa}
                          onChange={e => updateEtapa(secao.id, eIdx, e.target.value)}
                          rows={2}
                          placeholder="Descreva a etapa de preparo..."
                          className="flex-1 text-sm resize-none border-0 bg-transparent focus:bg-muted/30 focus:border rounded px-2 min-h-[2.5rem]"
                        />
                      ) : (
                        <p className="flex-1 text-sm py-1.5 leading-relaxed">
                          {etapa || <span className="italic text-muted-foreground">—</span>}
                        </p>
                      )}
                      {canEdit && (
                        <button type="button" onClick={() => removeEtapa(secao.id, eIdx)}
                          className="mt-1.5 h-6 w-6 flex items-center justify-center rounded opacity-0 group-hover:opacity-100 hover:bg-destructive/10 text-muted-foreground hover:text-destructive shrink-0 transition-opacity">
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  ))}
                  {canEdit && (
                    <div className="px-4 py-2">
                      <button type="button" onClick={() => addEtapa(secao.id)}
                        className="text-xs text-primary hover:underline flex items-center gap-1">
                        <Plus className="h-3 w-3" /> Adicionar etapa
                      </button>
                    </div>
                  )}
                  {!canEdit && secao.etapas.length === 0 && (
                    <p className="px-4 py-2 text-xs text-muted-foreground italic">Nenhuma etapa registrada.</p>
                  )}
                </div>
              </div>
            );
          })}

          {/* Observações Gerais */}
          {(canEdit || elab.observacoes_gerais) && (
            <div className="border rounded-xl overflow-hidden">
              <div className="bg-muted/40 px-4 py-2 border-b">
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Observações Gerais de Processo
                </span>
              </div>
              <div className="p-4">
                {canEdit ? (
                  <Textarea
                    value={elab.observacoes_gerais || ""}
                    onChange={e => setElab(el => ({ ...el, observacoes_gerais: e.target.value }))}
                    rows={3}
                    placeholder="Ex: produto sensível à temperatura — não ultrapassar 45°C na adição de ativos. Ajustar pH para 5,5–6,0 com NaOH 10% ou ácido cítrico 10%."
                    className="w-full text-sm border-0 bg-transparent resize-none focus:bg-muted/20 focus:border rounded px-0"
                  />
                ) : (
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{elab.observacoes_gerais}</p>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Aprovação */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Aprovação</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-4">
            <button
              type="button"
              disabled={!canEdit}
              onClick={() => canEdit && setForm(p => ({ ...p, status_aprovacao: "aprovado" }))}
              data-testid="ft-aprovado-btn"
              className={`flex items-center gap-2 px-4 py-2 rounded-lg border-2 text-sm font-semibold transition-all ${
                form.status_aprovacao === "aprovado"
                  ? "border-green-500 bg-green-50 text-green-700"
                  : "border-muted hover:border-green-300 text-muted-foreground"
              } ${!canEdit ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            >
              <CheckSquare className="h-4 w-4" /> APROVADO
            </button>
            <button
              type="button"
              disabled={!canEdit}
              onClick={() => canEdit && setForm(p => ({ ...p, status_aprovacao: "reprovado" }))}
              data-testid="ft-reprovado-btn"
              className={`flex items-center gap-2 px-4 py-2 rounded-lg border-2 text-sm font-semibold transition-all ${
                form.status_aprovacao === "reprovado"
                  ? "border-red-500 bg-red-50 text-red-700"
                  : "border-muted hover:border-red-300 text-muted-foreground"
              } ${!canEdit ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            >
              <XSquare className="h-4 w-4" /> REPROVADO
            </button>
          </div>
          <div className="max-w-xs">
            <Label className="text-xs text-muted-foreground">Resp. Técnico</Label>
            <Input
              value={form.resp_tecnico || ""}
              onChange={e => setForm(p => ({ ...p, resp_tecnico: e.target.value }))}
              placeholder="Nome do responsável técnico"
              className="mt-1 h-9"
              disabled={!canEdit}
              data-testid="ft-resp-tecnico"
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* ============ TESTS TAB (Unified form - all types at once) ============ */
function TestsTab({ devId, labResults, onRefresh, canEdit, reqId }) {
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    estabilidade: {},
    ph: {},
    viscosidade: {},
    sensorial: {},
    compatibilidade: {},
  });

  useEffect(() => {
    if (labResults) {
      setForm({
        estabilidade: labResults.estabilidade || {},
        ph: labResults.ph || {},
        viscosidade: labResults.viscosidade || {},
        sensorial: labResults.sensorial || {},
        compatibilidade: labResults.compatibilidade || {},
      });
    }
  }, [labResults]);

  const updateField = (section, key, value) => {
    setForm(prev => ({
      ...prev,
      [section]: { ...prev[section], [key]: value }
    }));
  };

  const saveAll = async () => {
    setSaving(true);
    try {
      await api.put(`/pd/developments/${devId}/lab-results`, form);
      toast.success("Testes salvos com sucesso!");
      onRefresh();
    } catch (err) {
      toast.error("Erro ao salvar testes");
    } finally {
      setSaving(false);
    }
  };

  const hasData = labResults && (
    Object.keys(labResults.estabilidade || {}).length > 0 ||
    Object.keys(labResults.ph || {}).length > 0 ||
    Object.keys(labResults.viscosidade || {}).length > 0 ||
    Object.keys(labResults.sensorial || {}).length > 0 ||
    Object.keys(labResults.compatibilidade || {}).length > 0
  );

  return (
    <div className="space-y-6">

      {/* R12: painel de estabilidade clonado — mesma fonte de dados da aba Estabilidades */}
      {reqId && (
        <>
          <div className="flex items-center gap-2">
            <TestTube className="h-4 w-4 text-primary" />
            <h3 className="text-base font-semibold">Estudo de Estabilidade</h3>
          </div>
          <StabilityGridPanel reqId={reqId} canEdit={canEdit} showStudyHeader={false} />
          <Separator />
        </>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">Características Padrão</h3>
        {hasData && labResults?.updated_by_name && (
          <span className="text-[11px] text-muted-foreground">
            Última atualização: {labResults.updated_by_name} • {new Date(labResults.updated_at).toLocaleString("pt-BR")}
          </span>
        )}
      </div>

      {/* ESTABILIDADE */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-purple-500" />
            Estabilidade
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground">Condição</Label>
              <Input value={form.estabilidade.condicao || ""} onChange={e => updateField("estabilidade", "condicao", e.target.value)} placeholder="Ex: 45°C / 90 dias" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Aspecto</Label>
              <Input value={form.estabilidade.aspecto || ""} onChange={e => updateField("estabilidade", "aspecto", e.target.value)} placeholder="Normal, separação, etc." disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Cor</Label>
              <Input value={form.estabilidade.cor || ""} onChange={e => updateField("estabilidade", "cor", e.target.value)} placeholder="Inalterada, escurecida, etc." disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Odor</Label>
              <Input value={form.estabilidade.odor || ""} onChange={e => updateField("estabilidade", "odor", e.target.value)} placeholder="Inalterado, alterado, etc." disabled={!canEdit} />
            </div>
            <div className="col-span-2">
              <Label className="text-xs text-muted-foreground">Observações</Label>
              <Textarea value={form.estabilidade.observacoes || ""} onChange={e => updateField("estabilidade", "observacoes", e.target.value)} placeholder="Notas adicionais" rows={2} disabled={!canEdit} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* pH */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-500" />
            pH
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground">Valor Medido</Label>
              <Input value={form.ph.valor_medido || ""} onChange={e => updateField("ph", "valor_medido", e.target.value)} placeholder="Ex: 5.5" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Faixa Aceitável</Label>
              <Input value={form.ph.faixa_aceitavel || ""} onChange={e => updateField("ph", "faixa_aceitavel", e.target.value)} placeholder="Ex: 5.0 - 6.0" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground"><FieldHint hint="Temperatura da amostra no momento da medição de pH. Deve ser registrada pois afeta o resultado.">Temperatura (°C)</FieldHint></Label>
              <Input value={form.ph.temperatura || ""} onChange={e => updateField("ph", "temperatura", e.target.value)} placeholder="Ex: 25" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Observações</Label>
              <Input value={form.ph.observacoes || ""} onChange={e => updateField("ph", "observacoes", e.target.value)} placeholder="Notas adicionais" disabled={!canEdit} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* VISCOSIDADE */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            Viscosidade
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground">Valor Medido</Label>
              <Input value={form.viscosidade.valor_medido || ""} onChange={e => updateField("viscosidade", "valor_medido", e.target.value)} placeholder="Ex: 15000" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Unidade</Label>
              <Input value={form.viscosidade.unidade || ""} onChange={e => updateField("viscosidade", "unidade", e.target.value)} placeholder="Ex: cP, mPa.s" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Spindle / Velocidade</Label>
              <Input value={form.viscosidade.spindle || ""} onChange={e => updateField("viscosidade", "spindle", e.target.value)} placeholder="Ex: S64 / 20 rpm" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground"><FieldHint hint="Temperatura da amostra durante a medição. Viscosidade varia com temperatura — registrar garante reprodutibilidade.">Temperatura (°C)</FieldHint></Label>
              <Input value={form.viscosidade.temperatura || ""} onChange={e => updateField("viscosidade", "temperatura", e.target.value)} placeholder="Ex: 25" disabled={!canEdit} />
            </div>
            <div className="col-span-2">
              <Label className="text-xs text-muted-foreground">Observações</Label>
              <Textarea value={form.viscosidade.observacoes || ""} onChange={e => updateField("viscosidade", "observacoes", e.target.value)} placeholder="Notas adicionais" rows={2} disabled={!canEdit} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* SENSORIAL */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-pink-500" />
            Sensorial
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground">Aspecto</Label>
              <Input value={form.sensorial.aspecto || ""} onChange={e => updateField("sensorial", "aspecto", e.target.value)} placeholder="Creme, líquido, gel, etc." disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Cor</Label>
              <Input value={form.sensorial.cor || ""} onChange={e => updateField("sensorial", "cor", e.target.value)} placeholder="Branca, translúcida, etc." disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Odor</Label>
              <Input value={form.sensorial.odor || ""} onChange={e => updateField("sensorial", "odor", e.target.value)} placeholder="Agradável, suave, etc." disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Toque</Label>
              <Input value={form.sensorial.toque || ""} onChange={e => updateField("sensorial", "toque", e.target.value)} placeholder="Sedoso, leve, pegajoso, etc." disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Espalhabilidade</Label>
              <Input value={form.sensorial.espalhabilidade || ""} onChange={e => updateField("sensorial", "espalhabilidade", e.target.value)} placeholder="Boa, excelente, etc." disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Observações</Label>
              <Input value={form.sensorial.observacoes || ""} onChange={e => updateField("sensorial", "observacoes", e.target.value)} placeholder="Notas adicionais" disabled={!canEdit} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* COMPATIBILIDADE */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            Compatibilidade
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="text-xs text-muted-foreground">Material Testado</Label>
              <Input value={form.compatibilidade.material_testado || ""} onChange={e => updateField("compatibilidade", "material_testado", e.target.value)} placeholder="Ex: PET, Alumínio, PP" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Tempo (dias)</Label>
              <Input value={form.compatibilidade.tempo_dias || ""} onChange={e => updateField("compatibilidade", "tempo_dias", e.target.value)} placeholder="Ex: 30, 60, 90" disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Resultado</Label>
              <Input value={form.compatibilidade.resultado || ""} onChange={e => updateField("compatibilidade", "resultado", e.target.value)} placeholder="Compatível, incompatível, etc." disabled={!canEdit} />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Observações</Label>
              <Input value={form.compatibilidade.observacoes || ""} onChange={e => updateField("compatibilidade", "observacoes", e.target.value)} placeholder="Notas adicionais" disabled={!canEdit} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Save Button */}
      {canEdit && (
        <div className="flex justify-end pt-2">
          <Button onClick={saveAll} disabled={saving} className="gap-2 px-8">
            <Save className="h-4 w-4" />
            {saving ? "Salvando..." : "Salvar Todos os Testes"}
          </Button>
        </div>
      )}
    </div>
  );
}

/* ============ SAMPLES TAB ============ */
function SamplesTab({ devId, samples, formulas, onRefresh, canEdit, productName }) {
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ formula_version: formulas[0]?.version || 1, sent_to_client: false, feedback: "" });
  const [editingId, setEditingId] = useState(null);
  const [editFeedback, setEditFeedback] = useState("");
  const [stockAlert, setStockAlert] = useState(null); // { found, items }
  const [checkingStock, setCheckingStock] = useState(false);

  const handleNewSample = async () => {
    if (!productName) { setShowCreate(true); return; }
    setCheckingStock(true);
    try {
      const { data } = await api.get("/pd/stock/check-product", { params: { produto_nome: productName } });
      if (data.found) {
        setStockAlert(data);
      } else {
        setShowCreate(true);
      }
    } catch {
      setShowCreate(true);
    } finally { setCheckingStock(false); }
  };

  const createSample = async () => {
    try {
      await api.post(`/pd/developments/${devId}/samples`, form);
      toast.success("Amostra registrada!");
      setShowCreate(false);
      setStockAlert(null);
      onRefresh();
    } catch (err) { toast.error("Erro ao registrar amostra"); }
  };

  const updateSample = async (sampleId, updates) => {
    try {
      await api.put(`/pd/samples/${sampleId}`, updates);
      toast.success("Amostra atualizada!");
      setEditingId(null);
      onRefresh();
    } catch (err) {
      const msg = formatApiError(err) || "Erro ao atualizar amostra";
      toast.error(msg);
    }
  };

  const getSampleStatus = (s) => {
    if (!s.sent_to_client) return { label: "Com P&D", color: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400", stage: 0 };
    if (s.client_approved === true) return { label: "Aprovada", color: "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300", stage: 3 };
    if (s.client_approved === false) return { label: "Reprovada pelo cliente", color: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300", stage: 3 };
    return { label: "Aguardando aprovação do cliente", color: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300", stage: 2 };
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold">Amostras ({samples.length})</h3>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={handleNewSample} className="gap-1.5" disabled={!canEdit || checkingStock}>
            {checkingStock ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} Nova Amostra
          </Button>
        </div>
      </div>

      {/* PD-16: Stock check alert */}
      {stockAlert && (
        <Card className="border-amber-300 bg-amber-50/50 dark:bg-amber-950/20">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="font-semibold text-sm text-amber-800 dark:text-amber-300">Produto encontrado no estoque do lab!</p>
                <p className="text-xs text-amber-700 dark:text-amber-400 mt-0.5">
                  Já existe {stockAlert.count} unidade(s) de "{productName}" em estoque ({stockAlert.items?.map(i => `${i.quantidade} ${i.unidade}`).join(", ")}).
                </p>
                <p className="text-xs text-muted-foreground mt-1">Deseja usar o estoque existente ou criar uma nova amostra?</p>
              </div>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => { setStockAlert(null); toast.info("Use o módulo de Estoque para dar baixa."); }} className="gap-1 border-amber-300 text-amber-700">
                <Package className="h-3 w-3" /> Usar estoque existente
              </Button>
              <Button size="sm" onClick={() => { setStockAlert(null); setShowCreate(true); }} className="gap-1">
                <Plus className="h-3 w-3" /> Criar nova amostra mesmo assim
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setStockAlert(null)}>Cancelar</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {showCreate && (
        <Card className="border-primary/50">
          <CardContent className="p-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Versão da Fórmula</Label>
                <Select value={String(form.formula_version)} onValueChange={v => setForm(p => ({ ...p, formula_version: parseInt(v) }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {formulas.length > 0 ? formulas.map(f => <SelectItem key={f.version} value={String(f.version)}>v{f.version} — {f.name}</SelectItem>) : <SelectItem value="1">v1</SelectItem>}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-3 pt-6">
                <Switch checked={form.sent_to_client} onCheckedChange={v => setForm(p => ({ ...p, sent_to_client: v }))} />
                <Label>Já entregue ao comercial</Label>
              </div>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={createSample}>Registrar Amostra</Button>
              <Button size="sm" variant="ghost" onClick={() => setShowCreate(false)}>Cancelar</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {samples.map(s => {
          const isEditing = editingId === s.id;
          const status = getSampleStatus(s);
          return (
            <Card key={s.id}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <span className="font-medium text-sm">Fórmula v{s.formula_version}</span>
                      <Badge className={`text-[11px] ${status.color}`}>{status.label}</Badge>
                    </div>

                    {/* Progress indicator */}
                    <div className="flex items-center gap-1 mb-3">
                      {[
                        { step: 1, label: "Com P&D", done: status.stage >= 1 },
                        { step: 2, label: "No Comercial", done: status.stage >= 2 },
                        { step: 3, label: "Decisão cliente", done: status.stage >= 3 },
                      ].map((st, i) => (
                        <React.Fragment key={st.step}>
                          <div className={`flex items-center gap-1 text-[10px] font-medium ${st.done ? "text-green-700" : "text-muted-foreground"}`}>
                            <div className={`h-4 w-4 rounded-full flex items-center justify-center text-[9px] font-bold ${st.done ? "bg-green-600 text-white" : "bg-muted border"}`}>
                              {st.step}
                            </div>
                            {st.label}
                          </div>
                          {i < 2 && <div className={`flex-1 h-px mx-1 ${st.done ? "bg-green-400" : "bg-border"}`} style={{ maxWidth: 24 }} />}
                        </React.Fragment>
                      ))}
                    </div>

                    {/* Feedback */}
                    {!isEditing ? (
                      s.feedback && (
                        <div className="bg-muted/50 p-2.5 rounded text-sm flex items-start gap-2">
                          <MessageSquare className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />
                          <p className="text-sm">{s.feedback}</p>
                        </div>
                      )
                    ) : (
                      <div className="space-y-2">
                        <Label className="text-xs">Feedback do cliente</Label>
                        <Textarea value={editFeedback} onChange={e => setEditFeedback(e.target.value)} rows={2} placeholder="Feedback do cliente..." />
                        <div className="flex gap-2">
                          <Button size="sm" onClick={() => updateSample(s.id, { feedback: editFeedback })} className="gap-1"><Save className="h-3 w-3" /> Salvar</Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>Cancelar</Button>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-col items-end gap-1.5 shrink-0">
                    {/* Stage 1 → 2: Entregar ao Comercial */}
                    {!s.sent_to_client && canEdit && (
                      <Button size="sm" variant="outline" onClick={() => updateSample(s.id, { sent_to_client: true })} className="gap-1 text-xs">
                        <Send className="h-3 w-3" /> Entregar ao Comercial
                      </Button>
                    )}
                    {/* Stage 2 → 3: Registrar decisão do cliente */}
                    {s.sent_to_client && s.client_approved == null && canEdit && (
                      <div className="flex gap-1.5">
                        <Button size="sm" variant="outline" className="gap-1 text-xs text-green-700 border-green-300 hover:bg-green-50"
                          onClick={() => { setEditingId(s.id); setEditFeedback(s.feedback || ""); updateSample(s.id, { client_approved: true }); }}>
                          <ThumbsUp className="h-3 w-3" /> Cliente aprovou
                        </Button>
                        <Button size="sm" variant="outline" className="gap-1 text-xs text-red-600 border-red-300 hover:bg-red-50"
                          onClick={() => { setEditingId(s.id); setEditFeedback(s.feedback || ""); updateSample(s.id, { client_approved: false }); }}>
                          <ThumbsDown className="h-3 w-3" /> Cliente reprovou
                        </Button>
                      </div>
                    )}
                    {/* Edit feedback */}
                    {!isEditing && canEdit && (
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => { setEditingId(s.id); setEditFeedback(s.feedback || ""); }}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                </div>

              </CardContent>
            </Card>
          );
        })}
      </div>

      {samples.length === 0 && !showCreate && (
        <EmptyState icon={Package} title="Nenhuma amostra registrada" subtitle="Registre amostras produzidas para entrega ao comercial" />
      )}
    </div>
  );
}

/* ============ MANIPULACAO ORDER (per-sample inline) ============ */
function ManipulacaoOrder({ formulaId, sampleVolume }) {
  const [items, setItems] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!formulaId) return;
    setLoading(true);
    api.get(`/pd/formulas/${formulaId}/items`)
      .then(r => setItems(Array.isArray(r.data) ? r.data : []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [formulaId]);

  if (loading) return <p className="text-xs text-muted-foreground py-2">Carregando composição...</p>;
  if (!items) return null;
  if (items.length === 0) return <p className="text-xs text-muted-foreground py-2">Fórmula sem ingredientes cadastrados.</p>;

  const totalPct = items.reduce((s, r) => s + (r.percentage || 0), 0);

  return (
    <div className="mt-3 rounded-md border bg-background overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-muted/50 border-b">
            <th className="text-left px-3 py-2 font-semibold">Ingrediente</th>
            <th className="text-left px-3 py-2 font-semibold">Fase</th>
            <th className="text-right px-3 py-2 font-semibold">%</th>
            <th className="text-right px-3 py-2 font-semibold">Qtd (g)</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => {
            const qty = ((row.percentage || 0) / 100) * sampleVolume;
            return (
              <tr key={row.id} className="border-b last:border-0 hover:bg-muted/20">
                <td className="px-3 py-1.5 font-medium">{row.ingredient_name}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{row.phase || "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono">{(row.percentage || 0).toFixed(3)}</td>
                <td className="px-3 py-1.5 text-right font-mono font-semibold">{qty.toFixed(4)}</td>
              </tr>
            );
          })}
          <tr className="bg-muted/30 font-semibold">
            <td className="px-3 py-1.5" colSpan={2}>TOTAL</td>
            <td className="px-3 py-1.5 text-right font-mono">{totalPct.toFixed(3)}</td>
            <td className="px-3 py-1.5 text-right font-mono">{((totalPct / 100) * sampleVolume).toFixed(4)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/* ============ COSTS TAB — P&D view (ingredient costs + submit to Comercial) ============ */
function CostsTab({ devId, costVersions, formulas, formulaCostData, onRefresh, canEdit, canViewCommercial }) {
  const v1 = costVersions?.v1 || {};
  const v2summary = costVersions?.v2 || null;
  const totalFinal = costVersions?.total_final;
  const pdCostBlank = Boolean(costVersions?.pd_cost_analysis_required);
  const v1Status = v1.status || "rascunho";
  const isSubmitted = v1Status === "enviado";

  const [manualAdj, setManualAdj] = useState(v1.ingredient_cost_manual || 0);
  const [notes, setNotes] = useState(v1.notes || "");
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setManualAdj(v1.ingredient_cost_manual || 0);
    setNotes(v1.notes || "");
  }, [v1.ingredient_cost_manual, v1.notes]);

  const latestFormula = formulas && formulas.length > 0 ? formulas[0] : null;

  const saveV1 = async () => {
    setSaving(true);
    try {
      await api.put(`/pd/developments/${devId}/cost-versions/v1`, {
        ingredient_cost_manual: parseFloat(manualAdj) || 0,
        notes,
      });
      toast.success("Rascunho de custo salvo.");
      onRefresh();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao salvar custo."); }
    finally { setSaving(false); }
  };

  const submitV1 = async () => {
    setSubmitting(true);
    try {
      await api.post(`/pd/developments/${devId}/cost-versions/v1/submit`);
      toast.success("Custo v1 enviado para análise comercial.");
      onRefresh();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao enviar."); }
    finally { setSubmitting(false); }
  };

  const v1StatusConfig = {
    rascunho: { label: "Rascunho", icon: Clock4, cls: "bg-slate-500/10 text-slate-400 border-slate-500/20" },
    enviado:  { label: "Enviado para Comercial", icon: CheckCircle, cls: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20" },
  }[v1Status] || { label: v1Status, icon: AlertCircle, cls: "bg-amber-500/10 text-amber-600 border-amber-500/20" };

  const v2StatusConfig = !v2summary ? null : {
    rascunho:   { label: "Comercial em análise", icon: Clock4, cls: "bg-sky-500/10 text-sky-600 border-sky-500/20" },
    finalizado: { label: "Custo final disponível", icon: CheckCircle2, cls: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20" },
  }[v2summary.status] || { label: v2summary.status, icon: AlertCircle, cls: "bg-slate-500/10 text-slate-400 border-slate-500/20" };

  return (
    <div className="space-y-6">
      {/* Status header */}
      <div className="flex items-center gap-3 flex-wrap">
        <h3 className="text-base font-semibold flex items-center gap-2">
          <Layers className="h-4 w-4 text-cyan-500" />
          Custo P&D — v1
        </h3>
        <Badge className={`border gap-1.5 ${v1StatusConfig.cls}`}>
          <v1StatusConfig.icon className="h-3 w-3" />
          {v1StatusConfig.label}
        </Badge>
        {v1.submitted_at && (
          <span className="text-xs text-muted-foreground">
            por {v1.submitted_by_name} em {new Date(v1.submitted_at).toLocaleDateString("pt-BR")}
          </span>
        )}
        {v2StatusConfig && (
          <Badge className={`border gap-1.5 ${v2StatusConfig.cls}`}>
            <v2StatusConfig.icon className="h-3 w-3" />
            {v2StatusConfig.label}
          </Badge>
        )}
      </div>

      {pdCostBlank && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-semibold">Custo P&D em branco</p>
            <p className="text-xs">
              Revise a formula, os custos de materia-prima e qualquer ajuste manual antes de enviar para analise comercial.
            </p>
          </div>
        </div>
      )}

      {/* Formula ingredient cost table (auto) */}
      {latestFormula && (
        <Card className="border-green-200 dark:border-green-900">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Beaker className="h-4 w-4 text-green-600" />
                Custo de Ingredientes — Fórmula v{latestFormula.version} ({latestFormula.name})
              </CardTitle>
              <Badge variant="outline" className="text-[10px] text-green-600 border-green-300">Auto-calculado</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="border rounded-md overflow-hidden mb-4">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-[#0A0A0B] text-white text-xs">
                    <th className="text-left p-2 font-medium">Ingrediente</th>
                    <th className="text-right p-2 font-medium w-24">% Fórmula</th>
                    <th className="text-right p-2 font-medium w-28">R$/Kg</th>
                    <th className="text-right p-2 font-medium w-24">Custo R$</th>
                    <th className="text-right p-2 font-medium w-24">% Custo</th>
                  </tr>
                </thead>
                <tbody>
                  {(latestFormula.items || []).map(item => {
                    const totalC = (latestFormula.items || []).reduce((s, it) => s + (it.cost_brl || 0), 0);
                    const pct = totalC > 0 ? ((item.cost_brl || 0) / totalC * 100) : 0;
                    return (
                      <tr key={item.id} className="border-t">
                        <td className="p-2">{item.ingredient_name}</td>
                        <td className="p-2 text-right font-mono text-xs">{(item.percentage || 0).toFixed(3)}</td>
                        <td className="p-2 text-right font-mono text-xs">{(item.price_per_kg || 0).toFixed(2)}</td>
                        <td className="p-2 text-right font-mono text-xs">{(item.cost_brl || 0).toFixed(4)}</td>
                        <td className="p-2 text-right font-mono text-xs">{pct.toFixed(1)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {formulaCostData && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-lg border p-3 text-center">
                  <div className="text-xs text-muted-foreground mb-1">Custo/Kg (R$)</div>
                  <div className="text-lg font-bold">{Number(formulaCostData.total_cost_per_kg || 0).toFixed(4)}</div>
                </div>
                <div className="rounded-lg border p-3 text-center bg-green-50 dark:bg-green-950">
                  <div className="text-xs text-muted-foreground mb-1">Custo Unitário</div>
                  <div className="text-lg font-bold text-green-700">R$ {Number(formulaCostData.custo_unitario || 0).toFixed(2)}</div>
                  {formulaCostData.volume > 0 && (
                    <div className="text-[10px] text-muted-foreground">{formulaCostData.volume} {formulaCostData.volume_unit}</div>
                  )}
                </div>
                {formulaCostData.indice_perdas > 0 && (
                  <div className="rounded-lg border p-3 text-center bg-orange-50 dark:bg-orange-950">
                    <div className="text-xs text-muted-foreground mb-1">c/ Perdas ({formulaCostData.indice_perdas}%)</div>
                    <div className="text-lg font-bold text-orange-700">R$ {Number(formulaCostData.custo_com_perdas || 0).toFixed(2)}</div>
                  </div>
                )}
                <div className="rounded-lg border p-3 text-center">
                  <div className="text-xs text-muted-foreground mb-1">Cotação US$</div>
                  <div className="text-lg font-bold">{Number(formulaCostData.cotacao_usd || 0).toFixed(2)}</div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Manual adjustment + notes (editable only when rascunho) */}
      <Card className={isSubmitted ? "opacity-70" : ""}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Ajuste Manual de Custo de Ingredientes</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <Label className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                <DollarSign className="h-3.5 w-3.5" /> Ajuste manual (R$)
              </Label>
              <Input type="number" step="0.01" value={manualAdj} disabled={isSubmitted || !canEdit}
                onChange={e => setManualAdj(e.target.value)} />
              <p className="text-[11px] text-muted-foreground mt-1">
                Valor somado ao custo auto-calculado da fórmula. Use para MP cotada fora do sistema.
              </p>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground mb-1 block">Observações</Label>
              <Input value={notes} disabled={isSubmitted || !canEdit} onChange={e => setNotes(e.target.value)}
                placeholder="Justificativa do ajuste, fornecedor, etc." />
            </div>
          </div>

          <div className="flex items-center justify-between rounded-lg border p-3 bg-muted/30">
            <span className="text-sm font-medium">Total v1 (ingredientes):</span>
            <span className="text-xl font-bold text-green-700">
              R$ {((v1.ingredient_cost_auto || formulaCostData?.total_cost_per_kg || 0) + (parseFloat(manualAdj) || 0)).toFixed(4)}
            </span>
          </div>

          {!isSubmitted && canEdit && (
            <div className="flex gap-2">
              <Button variant="outline" onClick={saveV1} disabled={saving} className="flex-1 gap-1.5">
                <Save className="h-4 w-4" />
                {saving ? "Salvando..." : "Salvar Rascunho"}
              </Button>
              <Button onClick={submitV1} disabled={submitting} className="flex-1 gap-1.5 bg-emerald-600 hover:bg-emerald-700">
                <Send className="h-4 w-4" />
                {submitting ? "Enviando..." : "Enviar para Comercial"}
              </Button>
            </div>
          )}

          {isSubmitted && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 dark:bg-emerald-950 dark:border-emerald-900 p-3 text-sm text-emerald-700 dark:text-emerald-300">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              Custo v1 enviado e bloqueado para edição. Aguardando análise comercial.
            </div>
          )}
        </CardContent>
      </Card>

      {/* Final cost (shown to P&D only when v2 is finalized) */}
      {totalFinal != null && (
        <Card className="border-2 border-emerald-500/30 bg-emerald-50/50 dark:bg-emerald-950/30">
          <CardContent className="pt-5 pb-5">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                <div>
                  <p className="font-semibold text-sm">Custo Final Aprovado pelo Comercial</p>
                  <p className="text-xs text-muted-foreground">
                    Finalizado em {v2summary?.finalized_at ? new Date(v2summary.finalized_at).toLocaleDateString("pt-BR") : "—"}
                  </p>
                </div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-emerald-700">R$ {totalFinal.toFixed(2)}</div>
                <div className="text-[11px] text-muted-foreground">custo total unitário</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* PD-07: Per-formula cost snapshots */}
      {formulas.map(f => (
        <FormulaCostVersionsPanel key={f.id} formula={f} canViewCommercial={canViewCommercial} canEdit={canEdit} />
      ))}
    </div>
  );
}

/* ============ PD-07: FORMULA COST VERSIONS PANEL ============ */
function FormulaCostVersionsPanel({ formula, canViewCommercial, canEdit }) {
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showSave, setShowSave] = useState(false);
  const [saveForm, setSaveForm] = useState({ custo_embalagem: "", custo_mao_obra: "" });
  const [saving, setSaving] = useState(false);

  const fetchVersions = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/pd/formulas/${formula.id}/costs`);
      setVersions(Array.isArray(data) ? data : []);
    } catch { setVersions([]); } finally { setLoading(false); }
  }, [formula.id]);

  useEffect(() => { fetchVersions(); }, [fetchVersions]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.post(`/pd/formulas/${formula.id}/costs`, {
        custo_embalagem: parseFloat(saveForm.custo_embalagem) || 0,
        custo_mao_obra: parseFloat(saveForm.custo_mao_obra) || 0,
      });
      toast.success("Versão de custo salva!");
      setShowSave(false);
      setSaveForm({ custo_embalagem: "", custo_mao_obra: "" });
      fetchVersions();
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao salvar versão");
    } finally { setSaving(false); }
  };

  return (
    <Card className="border-purple-200/50">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <History className="h-3.5 w-3.5 text-purple-500" />
            Versões de Custo — {formula.name}
            <Badge variant="outline" className="text-[9px]">v{formula.version}</Badge>
          </CardTitle>
          {canEdit && (
            <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={() => setShowSave(s => !s)}>
              <Plus className="h-3 w-3" /> Salvar versão de custo
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {showSave && (
          <div className="p-3 border rounded-md bg-muted/30 space-y-2">
            {canViewCommercial && (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-xs">Custo Embalagem (R$/un)</Label>
                  <Input type="number" step="0.01" value={saveForm.custo_embalagem} onChange={e => setSaveForm(f => ({ ...f, custo_embalagem: e.target.value }))} className="h-7 text-xs mt-0.5" placeholder="0.00" />
                </div>
                <div>
                  <Label className="text-xs">Custo Mão de Obra (R$/un)</Label>
                  <Input type="number" step="0.01" value={saveForm.custo_mao_obra} onChange={e => setSaveForm(f => ({ ...f, custo_mao_obra: e.target.value }))} className="h-7 text-xs mt-0.5" placeholder="0.00" />
                </div>
              </div>
            )}
            {!canViewCommercial && (
              <p className="text-xs text-muted-foreground italic">Snapshot de custo de MP gerado automaticamente a partir dos itens da fórmula.</p>
            )}
            <div className="flex gap-2">
              <Button size="sm" onClick={handleSave} disabled={saving} className="gap-1.5 h-7 text-xs">
                <Save className="h-3 w-3" /> {saving ? "Salvando..." : "Salvar Snapshot"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setShowSave(false)} className="h-7 text-xs">Cancelar</Button>
            </div>
          </div>
        )}
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Carregando...</div>
        ) : versions.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">Nenhuma versão de custo registrada ainda.</p>
        ) : (
          <div className="space-y-2">
            {versions.map((v, i) => (
              <div key={v.id} className={`flex items-start gap-3 p-2 rounded border ${i === 0 ? "border-purple-200 bg-purple-50/30 dark:bg-purple-950/20" : "bg-muted/20"}`}>
                <div className="flex flex-col items-center mt-0.5">
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold border ${i === 0 ? "bg-purple-500 text-white border-purple-500" : "bg-muted text-muted-foreground border-border"}`}>
                    v{v.versao}
                  </div>
                  {i < versions.length - 1 && <div className="w-px flex-1 bg-border mt-0.5" style={{ minHeight: 8 }} />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-green-700">MP: R$ {(v.custo_mp_total || 0).toFixed(2)}</span>
                    {canViewCommercial && v.custo_embalagem != null && (
                      <>
                        <span className="text-xs text-muted-foreground">Embal.: R$ {(v.custo_embalagem || 0).toFixed(2)}</span>
                        <span className="text-xs text-muted-foreground">M.O.: R$ {(v.custo_mao_obra || 0).toFixed(2)}</span>
                        <span className="text-xs font-bold text-primary">Total: R$ {(v.custo_total || 0).toFixed(2)}</span>
                      </>
                    )}
                    {i === 0 && <Badge className="text-[9px] bg-purple-500/10 text-purple-700 border-purple-300">Mais recente</Badge>}
                  </div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    {v.created_by_name && <>{v.created_by_name} • </>}{new Date(v.created_at).toLocaleDateString("pt-BR")}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ============ COMERCIAL TAB — Commercial view (full v1 + v2 inputs) ============ */
function ComercialTab({ devId, costVersions, formulaCostData, onRefresh, canFinalize }) {
  const v1 = costVersions?.v1 || {};
  const v2 = costVersions?.v2 || {};
  const v1Status = v1.status || "rascunho";
  const v2Status = v2.status || null;
  const isFinalized = v2Status === "finalizado";
  const totalFinal = costVersions?.total_final || 0;

  const [form, setForm] = useState({
    packaging_cost: v2.packaging_cost || 0,
    labor_cost: v2.labor_cost || 0,
    overhead_cost: v2.overhead_cost || 0,
    other_cost: v2.other_cost || 0,
    notes: v2.notes || "",
  });
  const [saving, setSaving] = useState(false);
  const [finalizing, setFinalizing] = useState(false);

  useEffect(() => {
    setForm({
      packaging_cost: v2.packaging_cost || 0,
      labor_cost: v2.labor_cost || 0,
      overhead_cost: v2.overhead_cost || 0,
      other_cost: v2.other_cost || 0,
      notes: v2.notes || "",
    });
  }, [v2.packaging_cost, v2.labor_cost, v2.overhead_cost, v2.other_cost, v2.notes]);

  const v2Total = (parseFloat(form.packaging_cost) || 0) + (parseFloat(form.labor_cost) || 0)
    + (parseFloat(form.overhead_cost) || 0) + (parseFloat(form.other_cost) || 0);
  const previewTotal = (v1.total || 0) + v2Total;

  const saveV2 = async () => {
    setSaving(true);
    try {
      await api.put(`/pd/developments/${devId}/cost-versions/v2`, {
        packaging_cost: parseFloat(form.packaging_cost) || 0,
        labor_cost: parseFloat(form.labor_cost) || 0,
        overhead_cost: parseFloat(form.overhead_cost) || 0,
        other_cost: parseFloat(form.other_cost) || 0,
        notes: form.notes,
      });
      toast.success("Custos comerciais salvos.");
      onRefresh();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao salvar."); }
    finally { setSaving(false); }
  };

  const finalizeV2 = async () => {
    setFinalizing(true);
    try {
      await api.post(`/pd/developments/${devId}/cost-versions/v2/finalize`);
      toast.success("Custo aprovado pelo Comercial e comunicado ao P&D.");
      onRefresh();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao finalizar."); }
    finally { setFinalizing(false); }
  };

  if (v1Status !== "enviado") {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <Clock4 className="h-7 w-7 text-muted-foreground" />
        </div>
        <p className="font-medium">Aguardando custo v1 do P&D</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          O setor de P&D ainda não enviou o custo de ingredientes. Assim que o custo v1 for submetido, você poderá preencher os custos comerciais aqui.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <h3 className="text-base font-semibold flex items-center gap-2">
          <Building2 className="h-4 w-4 text-sky-500" />
          Análise Comercial — Custo v2
        </h3>
        {v2Status && (
          <Badge className={`border gap-1.5 ${v2Status === "finalizado"
            ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
            : "bg-sky-500/10 text-sky-600 border-sky-500/20"}`}>
            {v2Status === "finalizado" ? <CheckCircle2 className="h-3 w-3" /> : <Clock4 className="h-3 w-3" />}
            {v2Status === "finalizado" ? "Finalizado" : "Rascunho"}
          </Badge>
        )}
        {isFinalized && v2.finalized_at && (
          <span className="text-xs text-muted-foreground">
            por {v2.finalized_by_name} em {new Date(v2.finalized_at).toLocaleDateString("pt-BR")}
          </span>
        )}
      </div>

      {/* V1 summary (read-only for Comercial) */}
      <Card className="border-green-200/50 dark:border-green-900/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2 text-muted-foreground">
            <Beaker className="h-3.5 w-3.5 text-green-600" />
            Custo P&D (v1 — recebido e bloqueado)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-lg border p-3 text-center">
              <div className="text-xs text-muted-foreground mb-1">Ingredientes Auto</div>
              <div className="font-bold text-sm">R$ {(v1.ingredient_cost_auto || 0).toFixed(4)}</div>
            </div>
            {(v1.ingredient_cost_manual || 0) > 0 && (
              <div className="rounded-lg border p-3 text-center">
                <div className="text-xs text-muted-foreground mb-1">Ajuste Manual</div>
                <div className="font-bold text-sm">R$ {(v1.ingredient_cost_manual || 0).toFixed(4)}</div>
              </div>
            )}
            <div className="rounded-lg border bg-green-50 dark:bg-green-950 p-3 text-center col-span-2">
              <div className="text-xs text-muted-foreground mb-1">Total v1 (ingredientes)</div>
              <div className="font-bold text-lg text-green-700">R$ {(v1.total || 0).toFixed(4)}</div>
            </div>
          </div>
          {v1.notes && (
            <p className="mt-3 text-xs text-muted-foreground italic border-l-2 border-green-300 pl-2">{v1.notes}</p>
          )}
          {formulaCostData && (
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-2">
              <div className="rounded-lg border p-2.5 text-center">
                <div className="text-[10px] text-muted-foreground mb-0.5">Custo Unit. (fórmula)</div>
                <div className="font-bold text-sm">R$ {formulaCostData.custo_unitario.toFixed(2)}</div>
                <div className="text-[10px] text-muted-foreground">{formulaCostData.volume} {formulaCostData.volume_unit}</div>
              </div>
              {formulaCostData.indice_perdas > 0 && (
                <div className="rounded-lg border p-2.5 text-center">
                  <div className="text-[10px] text-muted-foreground mb-0.5">c/ Perdas ({formulaCostData.indice_perdas}%)</div>
                  <div className="font-bold text-sm text-orange-600">R$ {formulaCostData.custo_com_perdas.toFixed(2)}</div>
                </div>
              )}
              <div className="rounded-lg border p-2.5 text-center">
                <div className="text-[10px] text-muted-foreground mb-0.5">Cotação US$</div>
                <div className="font-bold text-sm">{formulaCostData.cotacao_usd.toFixed(2)}</div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* V2 inputs */}
      <Card className={isFinalized ? "opacity-75" : ""}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <ShoppingCart className="h-4 w-4 text-sky-600" />
            Custos Adicionais / Analise Comercial
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {[
              { key: "packaging_cost", label: "Embalagem (R$)", icon: Package, color: "text-amber-500" },
              { key: "labor_cost", label: "Mão de Obra (R$)", icon: DollarSign, color: "text-sky-500" },
              { key: "overhead_cost", label: "Overhead / Fixos (R$)", icon: Building2, color: "text-violet-500" },
              { key: "other_cost", label: "Outros (R$)", icon: Layers, color: "text-rose-500" },
            ].map(({ key, label, icon: Icon, color }) => (
              <div key={key}>
                <Label className={`flex items-center gap-1.5 text-xs mb-1 ${color}`}>
                  <Icon className="h-3.5 w-3.5" /> {label}
                </Label>
                <Input type="number" step="0.01" value={form[key]} disabled={isFinalized}
                  onChange={e => setForm(p => ({ ...p, [key]: e.target.value }))} />
              </div>
            ))}
          </div>

          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">Observações da análise comercial</Label>
            <Input value={form.notes} disabled={isFinalized} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
              placeholder="Fornecedor, cotação, condições de pagamento, etc." />
          </div>

          <Separator />

          {/* Cost breakdown summary */}
          <div className="rounded-lg border bg-muted/20 p-4 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Ingredientes P&D (v1)</span>
              <span className="font-mono">R$ {(v1.total || 0).toFixed(4)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Embalagem</span>
              <span className="font-mono">R$ {(parseFloat(form.packaging_cost) || 0).toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Mão de Obra</span>
              <span className="font-mono">R$ {(parseFloat(form.labor_cost) || 0).toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Overhead / Fixos</span>
              <span className="font-mono">R$ {(parseFloat(form.overhead_cost) || 0).toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Outros</span>
              <span className="font-mono">R$ {(parseFloat(form.other_cost) || 0).toFixed(2)}</span>
            </div>
            <Separator />
            <div className="flex justify-between font-bold text-base">
              <span>Total Final</span>
              <span className="text-emerald-700">R$ {(isFinalized ? totalFinal : previewTotal).toFixed(2)}</span>
            </div>
          </div>

          {!isFinalized && (
            <div className="flex gap-2">
              <Button variant="outline" onClick={saveV2} disabled={saving} className="flex-1 gap-1.5">
                <Save className="h-4 w-4" />
                {saving ? "Salvando..." : "Salvar Rascunho"}
              </Button>
              <Button onClick={finalizeV2} disabled={finalizing || !v2Status || !canFinalize} className="flex-1 gap-1.5 bg-emerald-600 hover:bg-emerald-700">
                <CheckCircle2 className="h-4 w-4" />
                {finalizing ? "Finalizando..." : "Aprovar e Finalizar Custo"}
              </Button>
            </div>
          )}

          {!canFinalize && !isFinalized && (
            <p className="text-xs text-center text-muted-foreground">
              Somente Comercial pode aprovar e finalizar o custo para liberar a atualizacao do P&D.
            </p>
          )}

          {!v2Status && (
            <p className="text-xs text-center text-muted-foreground">Salve um rascunho antes de finalizar.</p>
          )}

          {isFinalized && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 dark:bg-emerald-950 dark:border-emerald-900 p-3 text-sm text-emerald-700 dark:text-emerald-300">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              Custo aprovado pelo Comercial e comunicado ao P&D. Custo total: <strong>R$ {totalFinal.toFixed(2)}</strong>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ============ DOCUMENTS TAB ============ */
function DocumentsTab({ devId, documents, onRefresh, canEdit }) {
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ doc_type: "Ficha Técnica", file_url: "", file_name: "" });
  const [uploading, setUploading] = useState(false);

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await api.post("/upload", formData, { headers: { "Content-Type": "multipart/form-data" } });
      setForm(p => ({ ...p, file_url: `/api/files/${res.data.id}`, file_name: file.name }));
      toast.success("Arquivo enviado!");
    } catch (err) { toast.error("Erro ao enviar arquivo"); }
    finally { setUploading(false); }
  };

  const saveDocument = async () => {
    if (!form.file_url) return toast.error("Envie um arquivo primeiro");
    try {
      await api.post(`/pd/developments/${devId}/documents`, form);
      toast.success("Documento registrado!");
      setShowCreate(false);
      setForm({ doc_type: "Ficha Técnica", file_url: "", file_name: "" });
      onRefresh();
    } catch (err) { toast.error("Erro ao registrar documento"); }
  };

  const deleteDoc = async (docId) => {
    try { await api.delete(`/pd/documents/${docId}`); onRefresh(); }
    catch (err) { toast.error("Erro ao remover"); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">Documentos & Laudos ({documents.length})</h3>
        <Button size="sm" onClick={() => setShowCreate(true)} className="gap-1.5" disabled={!canEdit}>
          <Plus className="h-3.5 w-3.5" /> Novo Documento
        </Button>
      </div>

      {showCreate && (
        <Card className="border-primary/50">
          <CardContent className="p-4 space-y-3">
            <div>
              <Label>Tipo de Documento</Label>
              <Select value={form.doc_type} onValueChange={v => setForm(p => ({ ...p, doc_type: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {DOC_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Arquivo</Label>
              <Input type="file" onChange={handleFileUpload} disabled={uploading} className="mt-1" />
              {uploading && <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Enviando...</p>}
              {form.file_name && <p className="text-xs text-green-600 mt-1 flex items-center gap-1"><CheckCircle2 className="h-3 w-3" /> {form.file_name}</p>}
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={saveDocument} disabled={!form.file_url}>Registrar Documento</Button>
              <Button size="sm" variant="ghost" onClick={() => setShowCreate(false)}>Cancelar</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {documents.map(doc => (
          <Card key={doc.id}>
            <CardContent className="p-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <div className="h-10 w-10 rounded-md bg-muted flex items-center justify-center shrink-0">
                  <FileText className="h-5 w-5 text-muted-foreground" />
                </div>
                <div className="min-w-0">
                  <span className="font-medium text-sm truncate block">{doc.file_name || doc.doc_type}</span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <Badge variant="outline" className="text-[10px]">{doc.doc_type}</Badge>
                    <span className="text-[10px] text-muted-foreground">
                      {doc.uploaded_by_name} • {new Date(doc.uploaded_at).toLocaleDateString("pt-BR")}
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {doc.file_url && (
                  <a href={doc.file_url.startsWith("/api") ? `${BACKEND_URL}${doc.file_url}` : doc.file_url}
                    target="_blank" rel="noopener noreferrer">
                    <Button size="sm" variant="outline" className="gap-1 text-xs">
                      <Download className="h-3 w-3" /> Download
                    </Button>
                  </a>
                )}
                {canEdit && (
                  <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-red-500" onClick={() => deleteDoc(doc.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {documents.length === 0 && !showCreate && (
        <EmptyState icon={FileText} title="Nenhum documento registrado" subtitle="Anexe fichas técnicas, laudos, especificações e outros documentos" />
      )}
    </div>
  );
}

/* ============ SKU FIELD ============ */
function SkuField({ reqId, currentSku, canEdit, onRefresh }) {
  const [editing, setEditing] = useState(false);
  const [sku, setSku] = useState(currentSku || "");
  const [saving, setSaving] = useState(false);

  const saveSku = async () => {
    setSaving(true);
    try {
      await api.put(`/pd/requests/${reqId}`, { sku });
      toast.success("SKU salvo!");
      setEditing(false);
      onRefresh();
    } catch (err) { toast.error("Erro ao salvar SKU"); }
    finally { setSaving(false); }
  };

  return (
    <div className="pt-2 border-t mt-2">
      <div className="flex items-center justify-between">
        <Label className="text-xs text-muted-foreground font-medium flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-green-500" />
          SKU (Produção)
        </Label>
        {canEdit && !editing && (
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)} className="text-xs gap-1 h-6">
            <Pencil className="h-3 w-3" /> {currentSku ? "Editar" : "Definir SKU"}
          </Button>
        )}
      </div>
      {!editing ? (
        currentSku ? (
          <p className="text-sm font-mono font-bold mt-1">{currentSku}</p>
        ) : (
          <p className="text-xs text-muted-foreground italic mt-1">SKU será definido para produção</p>
        )
      ) : (
        <div className="flex gap-2 mt-1">
          <Input value={sku} onChange={e => setSku(e.target.value)} placeholder="Ex: BSP-FLORAL-001" className="h-8 text-sm font-mono" />
          <Button size="sm" className="h-8" onClick={saveSku} disabled={saving}><Save className="h-3 w-3" /></Button>
          <Button size="sm" variant="ghost" className="h-8" onClick={() => { setEditing(false); setSku(currentSku || ""); }}><X className="h-3 w-3" /></Button>
        </div>
      )}
    </div>
  );
}

/* ============ EMPTY STATE ============ */
function EmptyState({ icon: Icon, title, subtitle }) {
  return (
    <div className="text-center py-16">
      <Icon className="h-14 w-14 mx-auto mb-4 text-muted-foreground/20" />
      <h4 className="font-medium mb-1">{title}</h4>
      <p className="text-xs text-muted-foreground">{subtitle}</p>
    </div>
  );
}

/* ============ PD-08: FORMULA PHASE EDITOR ============ */
function FormulaPhaseEditor({ formulaId, canEdit }) {
  const normalizePhase = useCallback((phase, index = 0) => ({
    id: phase?.id || `phase-${index}`,
    titulo: phase?.titulo || phase?.nome_fase || "",
    descricao: phase?.descricao || phase?.instrucoes || "",
    temperatura: phase?.temperatura || "",
    observacoes: phase?.observacoes || phase?.notas || "",
    ordem: phase?.ordem ?? index,
  }), []);
  const [phases, setPhases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({ titulo: "", descricao: "", temperatura: "" });
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  const fetchPhases = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/pd/formulas/${formulaId}/phases`);
      setPhases(Array.isArray(data) ? data.map((phase, index) => normalizePhase(phase, index)) : []);
    } catch { setPhases([]); } finally { setLoading(false); }
  }, [formulaId, normalizePhase]);

  useEffect(() => { fetchPhases(); }, [fetchPhases]);

  const addPhase = async () => {
    if (!addForm.titulo.trim()) return toast.error("Título da fase é obrigatório");
    setSaving(true);
    try {
      await api.post(`/pd/formulas/${formulaId}/phases`, {
        nome_fase: addForm.titulo.trim(),
        instrucoes: addForm.descricao?.trim() || "",
        temperatura: addForm.temperatura?.trim() || "",
      });
      setAddForm({ titulo: "", descricao: "", temperatura: "" });
      setShowAdd(false);
      await fetchPhases();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao adicionar fase"); }
    finally { setSaving(false); }
  };

  const saveEdit = async (phaseId) => {
    try {
      await api.put(`/pd/formula-phases/${phaseId}`, {
        nome_fase: editForm.titulo?.trim() || "",
        instrucoes: editForm.descricao?.trim() || "",
        temperatura: editForm.temperatura?.trim() || "",
      });
      setEditingId(null);
      await fetchPhases();
    } catch (err) { toast.error(formatApiError(err) || "Erro ao salvar"); }
  };

  const deletePhase = async (phaseId) => {
    if (!window.confirm("Remover esta fase?")) return;
    try { await api.delete(`/pd/formula-phases/${phaseId}`); await fetchPhases(); }
    catch (err) { toast.error(formatApiError(err) || "Erro ao remover"); }
  };

  const onDragEnd = async (result) => {
    if (!result.destination || result.destination.index === result.source.index) return;
    const reordered = Array.from(phases);
    const [moved] = reordered.splice(result.source.index, 1);
    reordered.splice(result.destination.index, 0, moved);
    setPhases(reordered);
    try {
      await api.put(`/pd/formulas/${formulaId}/phases/reorder`, { phase_ids: reordered.map(p => p.id) });
      await fetchPhases();
    } catch { fetchPhases(); }
  };

  if (loading) return <div className="flex items-center gap-2 text-xs text-muted-foreground py-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Carregando fases...</div>;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold flex items-center gap-1.5 text-muted-foreground uppercase tracking-wide">
          <ClipboardList className="h-3.5 w-3.5" /> Fases de Elaboração
        </span>
        {canEdit && (
          <Button size="sm" variant="ghost" className="h-6 text-xs gap-1" onClick={() => setShowAdd(s => !s)}>
            <Plus className="h-3 w-3" /> Adicionar fase
          </Button>
        )}
      </div>

      {showAdd && (
        <div className="p-2 border rounded bg-muted/30 space-y-2">
          <Input value={addForm.titulo} onChange={e => setAddForm(f => ({ ...f, titulo: e.target.value }))} placeholder="Título da fase (ex: Fase A, Aquosa...)" className="h-7 text-xs" />
          <div className="grid grid-cols-2 gap-2">
            <Input value={addForm.temperatura} onChange={e => setAddForm(f => ({ ...f, temperatura: e.target.value }))} placeholder="Temperatura (ex: 80°C)" className="h-7 text-xs" />
            <Textarea value={addForm.descricao} onChange={e => setAddForm(f => ({ ...f, descricao: e.target.value }))} placeholder="Instruções de elaboração..." rows={2} className="text-xs" />
          </div>
          <div className="flex gap-1.5">
            <Button size="sm" className="h-7 text-xs gap-1" onClick={addPhase} disabled={saving}><Save className="h-3 w-3" /> Salvar</Button>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setShowAdd(false)}>Cancelar</Button>
          </div>
        </div>
      )}

      {phases.length === 0 && !showAdd && (
        <p className="text-xs text-muted-foreground italic py-1">Nenhuma fase definida. {canEdit ? "Adicione fases de elaboração para este produto." : ""}</p>
      )}

      <DragDropContext onDragEnd={onDragEnd}>
        <Droppable droppableId={`phases-${formulaId}`}>
          {(provided) => (
            <div ref={provided.innerRef} {...provided.droppableProps} className="space-y-1">
              {phases.map((phase, idx) => (
                <Draggable key={phase.id} draggableId={phase.id} index={idx} isDragDisabled={!canEdit}>
                  {(drag, snapshot) => (
                    <div
                      ref={drag.innerRef}
                      {...drag.draggableProps}
                      className={`flex items-start gap-2 p-2 rounded border text-xs ${snapshot.isDragging ? "bg-muted shadow-md" : "bg-background hover:bg-muted/30"}`}
                    >
                      {canEdit && (
                        <div {...drag.dragHandleProps} className="mt-0.5 cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground">
                          <Layers className="h-3.5 w-3.5" />
                        </div>
                      )}
                      <div className="flex items-center justify-center h-5 w-5 rounded-full bg-primary/10 text-primary font-bold text-[10px] shrink-0 mt-0.5">
                        {idx + 1}
                      </div>
                      {editingId === phase.id ? (
                        <div className="flex-1 space-y-1">
                          <Input value={editForm.titulo} onChange={e => setEditForm(f => ({ ...f, titulo: e.target.value }))} className="h-6 text-xs" />
                          <div className="grid grid-cols-2 gap-1">
                            <Input value={editForm.temperatura || ""} onChange={e => setEditForm(f => ({ ...f, temperatura: e.target.value }))} placeholder="Temp." className="h-6 text-xs" />
                            <Textarea value={editForm.descricao || ""} onChange={e => setEditForm(f => ({ ...f, descricao: e.target.value }))} rows={2} className="text-xs" />
                          </div>
                          <div className="flex gap-1">
                            <button onClick={() => saveEdit(phase.id)} className="text-green-600 hover:text-green-700"><Save className="h-3 w-3" /></button>
                            <button onClick={() => setEditingId(null)} className="text-muted-foreground hover:text-red-500"><X className="h-3 w-3" /></button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex-1 min-w-0">
                          <span className="font-semibold">{phase.titulo}</span>
                          {phase.temperatura && <span className="ml-1.5 text-muted-foreground">({phase.temperatura})</span>}
                          {phase.descricao && <p className="text-muted-foreground mt-0.5 whitespace-pre-wrap">{phase.descricao}</p>}
                        </div>
                      )}
                      {canEdit && editingId !== phase.id && (
                        <div className="flex gap-1 shrink-0">
                          <button onClick={() => { setEditingId(phase.id); setEditForm({ titulo: phase.titulo, descricao: phase.descricao || "", temperatura: phase.temperatura || "" }); }} className="text-muted-foreground hover:text-blue-500"><Pencil className="h-3 w-3" /></button>
                          <button onClick={() => deletePhase(phase.id)} className="text-muted-foreground hover:text-red-500"><Trash2 className="h-3 w-3" /></button>
                        </div>
                      )}
                    </div>
                  )}
                </Draggable>
              ))}
              {provided.placeholder}
            </div>
          )}
        </Droppable>
      </DragDropContext>
    </div>
  );
}

/* ============ PD-11: 9-STAGE PROGRESS TIMELINE ============ */
const PIPELINE_STAGES = [
  { id: "solicitacao", label: "Solicitação recebida", icon: ClipboardList, color: "text-blue-500" },
  { id: "contato_fornecedores", label: "Contato fornecedores", icon: Building2, color: "text-indigo-500" },
  { id: "formulacao", label: "Formulação", icon: Beaker, color: "text-purple-500" },
  { id: "testes", label: "Testes em Lab", icon: TestTube, color: "text-cyan-500" },
  { id: "ficha_tecnica", label: "Ficha Técnica", icon: FileText, color: "text-sky-500" },
  { id: "entregue_comercial", label: "Entregue ao Comercial", icon: Send, color: "text-amber-500" },
  { id: "enviada_cliente", label: "Enviada ao Cliente", icon: Package, color: "text-rose-500" },
  { id: "aprovacao_cliente", label: "Aprovação do Cliente", icon: ThumbsUp, color: "text-green-500" },
];

function computeTimelineStages(req, formulas = [], tests = [], samples = [], approval = null) {
  const s = req.status;
  const advanced = ["IN_TESTS", "WAITING_APPROVAL", "APPROVED", "COMPLETED"].includes(s);
  const veryAdvanced = ["WAITING_APPROVAL", "APPROVED", "COMPLETED"].includes(s);
  return [
    { ...PIPELINE_STAGES[0], done: true, current: s === "OPEN" },
    { ...PIPELINE_STAGES[1], done: s !== "OPEN", current: s === "IN_PROGRESS" && formulas.length === 0 },
    { ...PIPELINE_STAGES[2], done: formulas.length > 0, current: s === "IN_PROGRESS" && formulas.length > 0 },
    { ...PIPELINE_STAGES[3], done: advanced, current: s === "IN_TESTS" },
    { ...PIPELINE_STAGES[4], done: veryAdvanced, current: false },
    { ...PIPELINE_STAGES[5], done: veryAdvanced, current: s === "WAITING_APPROVAL" },
    { ...PIPELINE_STAGES[6], done: veryAdvanced && samples.length > 0, current: false },
    { ...PIPELINE_STAGES[7], done: ["APPROVED", "COMPLETED"].includes(s) || !!approval?.approved_by_client, current: ["APPROVED", "COMPLETED"].includes(s) },
  ];
}

function SampleProgressTimeline({ req, formulas, tests, samples, approval }) {
  const stages = computeTimelineStages(req, formulas, tests, samples, approval);
  return (
    <div className="space-y-0">
      {stages.map((stage, i) => {
        const Icon = stage.icon;
        const isLast = i === stages.length - 1;
        return (
          <div key={stage.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div className={`w-7 h-7 rounded-full flex items-center justify-center border-2 shrink-0 transition-all ${
                stage.done
                  ? "bg-green-500 border-green-500 text-white"
                  : stage.current
                  ? "bg-primary border-primary text-primary-foreground animate-pulse"
                  : "bg-muted border-border text-muted-foreground"
              }`}>
                {stage.done ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Icon className="h-3 w-3" />}
              </div>
              {!isLast && <div className={`w-px flex-1 my-0.5 ${stage.done ? "bg-green-400" : "bg-border"}`} style={{ minHeight: 16 }} />}
            </div>
            <div className={`pb-3 ${isLast ? "" : ""}`}>
              <p className={`text-xs font-medium leading-tight mt-1 ${stage.done ? "text-foreground" : stage.current ? "text-primary font-semibold" : "text-muted-foreground"}`}>
                {stage.label}
              </p>
              {stage.current && (
                <p className="text-[10px] text-primary/70 mt-0.5">Etapa atual</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ============ UPDATES TAB (Atualizações + Pendências) ============ */
const PENDING_TYPES = [
  { id: "fragrancia", label: "Fragrância", icon: "🌸" },
  { id: "mp", label: "Matéria-Prima", icon: "🧪" },
  { id: "insumo", label: "Insumo", icon: "📦" },
  { id: "amostra", label: "Amostra/Embalagem", icon: "🎁" },
  { id: "outro", label: "Outro", icon: "📌" },
];

const PENDING_STATUS_COLORS = {
  pendente: "bg-amber-500/10 text-amber-700 border-amber-300",
  atrasado: "bg-red-500/10 text-red-700 border-red-300",
  recebido: "bg-green-500/10 text-green-700 border-green-300",
  cancelado: "bg-slate-500/10 text-slate-600 border-slate-300",
};

function UpdatesTab({ reqId, updates, pending, onRefresh, canEdit }) {
  const [showNewUpdate, setShowNewUpdate] = useState(false);
  const [newUpdateMsg, setNewUpdateMsg] = useState("");
  const [newUpdateVisible, setNewUpdateVisible] = useState(true);
  const [newUpdateItemSolicitado, setNewUpdateItemSolicitado] = useState("");
  const [newUpdateFornecedor, setNewUpdateFornecedor] = useState("");
  const [newUpdatePrevisaoEntrega, setNewUpdatePrevisaoEntrega] = useState("");
  const [showNewPending, setShowNewPending] = useState(false);
  const [pendingForm, setPendingForm] = useState({
    tipo: "fragrancia",
    descricao: "",
    data_prevista: "",
    fornecedor: "",
    observacoes: "",
  });
  const [saving, setSaving] = useState(false);

  const addUpdate = async () => {
    if (!newUpdateMsg.trim()) return toast.error("Escreva a mensagem");
    setSaving(true);
    try {
      await api.post(`/pd/requests/${reqId}/updates`, {
        mensagem: newUpdateMsg,
        tipo: newUpdateItemSolicitado ? "material_request" : "observacao",
        visivel_comercial: newUpdateVisible,
        ...(newUpdateItemSolicitado && { item_solicitado: newUpdateItemSolicitado }),
        ...(newUpdateFornecedor && { fornecedor: newUpdateFornecedor }),
        ...(newUpdatePrevisaoEntrega && { previsao_entrega: newUpdatePrevisaoEntrega }),
      });
      toast.success("Atualização publicada");
      setNewUpdateMsg(""); setNewUpdateItemSolicitado(""); setNewUpdateFornecedor(""); setNewUpdatePrevisaoEntrega("");
      setShowNewUpdate(false);
      onRefresh();
    } catch (err) {
      toast.error("Erro ao publicar");
    } finally {
      setSaving(false);
    }
  };

  const markUpdateReceived = async (upId) => {
    try {
      await api.put(`/pd/updates/${upId}/received`);
      toast.success("Marcado como recebido");
      onRefresh();
    } catch (err) { toast.error("Erro ao marcar recebido"); }
  };

  const deleteUpdate = async (upId) => {
    if (!window.confirm("Remover atualização?")) return;
    try {
      await api.delete(`/pd/updates/${upId}`);
      onRefresh();
    } catch (err) { toast.error("Erro"); }
  };

  const addPending = async () => {
    if (!pendingForm.descricao.trim()) return toast.error("Descreva a pendência");
    setSaving(true);
    try {
      await api.post(`/pd/requests/${reqId}/pending`, {
        tipo: pendingForm.tipo,
        descricao: pendingForm.descricao,
        data_prevista: pendingForm.data_prevista || null,
        fornecedor: pendingForm.fornecedor,
        observacoes: pendingForm.observacoes,
      });
      toast.success("Pendência criada");
      setShowNewPending(false);
      setPendingForm({ tipo: "fragrancia", descricao: "", data_prevista: "", fornecedor: "", observacoes: "" });
      onRefresh();
    } catch (err) { toast.error("Erro"); }
    finally { setSaving(false); }
  };

  const markReceived = async (pId) => {
    try {
      await api.put(`/pd/pending/${pId}`, { status: "recebido" });
      toast.success("Marcado como recebido");
      onRefresh();
    } catch (err) { toast.error("Erro"); }
  };

  const cancelPending = async (pId) => {
    if (!window.confirm("Cancelar esta pendência?")) return;
    try {
      await api.put(`/pd/pending/${pId}`, { status: "cancelado" });
      onRefresh();
    } catch (err) { toast.error("Erro"); }
  };

  const deletePending = async (pId) => {
    if (!window.confirm("Remover pendência?")) return;
    try {
      await api.delete(`/pd/pending/${pId}`);
      onRefresh();
    } catch (err) { toast.error("Erro"); }
  };

  const activePending = pending.filter(p => p.status === "pendente" || p.status === "atrasado");
  const resolvedPending = pending.filter(p => p.status === "recebido" || p.status === "cancelado");

  return (
    <div className="space-y-5">
      {/* PENDING ITEMS SECTION */}
      <Card className="border-amber-300/40">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Hourglass className="h-4 w-4 text-amber-500" />
              Pendências de Solicitação
              {activePending.length > 0 && (
                <Badge className="bg-amber-500/20 text-amber-700 border-amber-300">{activePending.length} ativa(s)</Badge>
              )}
            </CardTitle>
            {canEdit && (
              <Button size="sm" onClick={() => setShowNewPending(true)} className="gap-1.5">
                <Plus className="h-3.5 w-3.5" /> Nova Pendência
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {showNewPending && (
            <Card className="border-primary/50 bg-muted/30">
              <CardContent className="p-3 space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs">Tipo</Label>
                    <Select value={pendingForm.tipo} onValueChange={(v) => setPendingForm(p => ({ ...p, tipo: v }))}>
                      <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {PENDING_TYPES.map(t => <SelectItem key={t.id} value={t.id}>{t.icon} {t.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-xs">Previsão de Recebimento</Label>
                    <Input type="date" value={pendingForm.data_prevista} onChange={(e) => setPendingForm(p => ({ ...p, data_prevista: e.target.value }))} className="h-8 text-sm" />
                  </div>
                  <div className="col-span-2">
                    <Label className="text-xs">Descrição *</Label>
                    <Input value={pendingForm.descricao} onChange={(e) => setPendingForm(p => ({ ...p, descricao: e.target.value }))} placeholder="Ex: Fragrância para Ginger" className="h-8 text-sm" />
                  </div>
                  <div>
                    <Label className="text-xs">Fornecedor</Label>
                    <Input value={pendingForm.fornecedor} onChange={(e) => setPendingForm(p => ({ ...p, fornecedor: e.target.value }))} className="h-8 text-sm" />
                  </div>
                  <div>
                    <Label className="text-xs">Observações</Label>
                    <Input value={pendingForm.observacoes} onChange={(e) => setPendingForm(p => ({ ...p, observacoes: e.target.value }))} className="h-8 text-sm" />
                  </div>
                </div>
                <div className="flex gap-2 pt-1">
                  <Button size="sm" onClick={addPending} disabled={saving}>{saving ? "Salvando..." : "Criar Pendência"}</Button>
                  <Button size="sm" variant="ghost" onClick={() => setShowNewPending(false)}>Cancelar</Button>
                </div>
              </CardContent>
            </Card>
          )}

          {activePending.length === 0 && !showNewPending && (
            <p className="text-xs text-muted-foreground italic text-center py-4">Nenhuma pendência ativa.</p>
          )}

          {activePending.map(p => {
            const status = p.status_calc || p.status;
            const typeInfo = PENDING_TYPES.find(t => t.id === p.tipo) || { icon: "📌", label: p.tipo };
            return (
              <div key={p.id} className={`flex items-center gap-3 p-3 rounded-md border ${status === "atrasado" ? "bg-red-50/40 dark:bg-red-950/10 border-red-200" : "bg-amber-50/30 dark:bg-amber-950/10 border-amber-200"}`}>
                <span className="text-xl">{typeInfo.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm">{p.descricao}</span>
                    <Badge variant="outline" className="text-[10px]">{typeInfo.label}</Badge>
                    <Badge className={`${PENDING_STATUS_COLORS[status]} text-[10px]`}>
                      {status === "atrasado" && <AlertTriangle className="h-2.5 w-2.5 mr-0.5" />}
                      {status}
                    </Badge>
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-3 flex-wrap">
                    <span>Solicitado em {new Date(p.data_solicitacao).toLocaleDateString("pt-BR")}</span>
                    {p.data_prevista && <span>• Previsão: {new Date(p.data_prevista).toLocaleDateString("pt-BR")}</span>}
                    {p.fornecedor && <span>• {p.fornecedor}</span>}
                  </div>
                  {p.observacoes && <p className="text-xs mt-1 italic">{p.observacoes}</p>}
                </div>
                {canEdit && (
                  <div className="flex items-center gap-1 shrink-0">
                    <Button size="sm" variant="outline" onClick={() => markReceived(p.id)} className="gap-1 h-7 text-xs">
                      <CheckCircle2 className="h-3 w-3" /> Recebido
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => cancelPending(p.id)} className="h-7 text-xs text-muted-foreground">
                      Cancelar
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => deletePending(p.id)} className="h-7 w-7 p-0 hover:text-red-500">
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                )}
              </div>
            );
          })}

          {resolvedPending.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">Ver {resolvedPending.length} pendência(s) resolvida(s)</summary>
              <div className="space-y-1 mt-2">
                {resolvedPending.map(p => {
                  const typeInfo = PENDING_TYPES.find(t => t.id === p.tipo) || { icon: "📌", label: p.tipo };
                  return (
                    <div key={p.id} className="flex items-center gap-2 text-xs p-2 border rounded bg-muted/20">
                      <span>{typeInfo.icon}</span>
                      <span className="line-through text-muted-foreground flex-1">{p.descricao}</span>
                      <Badge className={`${PENDING_STATUS_COLORS[p.status]} text-[10px]`}>{p.status}</Badge>
                      {p.data_recebido && <span className="text-[10px] text-muted-foreground">em {new Date(p.data_recebido).toLocaleDateString("pt-BR")}</span>}
                    </div>
                  );
                })}
              </div>
            </details>
          )}
        </CardContent>
      </Card>

      {/* TIMELINE */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Bell className="h-4 w-4 text-blue-500" />
              Atualizações do Desenvolvimento
              <span className="text-xs text-muted-foreground font-normal">({updates.length})</span>
            </CardTitle>
            {canEdit && (
              <Button size="sm" onClick={() => setShowNewUpdate(true)} className="gap-1.5">
                <Plus className="h-3.5 w-3.5" /> Nova Atualização
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Feed cronológico visível para o time comercial. Mantenha o CRM sincronizado sobre o status da amostra.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {showNewUpdate && (
            <div className="p-3 border rounded-md bg-muted/30 space-y-2">
              <Textarea
                value={newUpdateMsg}
                onChange={(e) => setNewUpdateMsg(e.target.value)}
                rows={3}
                placeholder="Ex: Solicitada fragrância para Ginger em 13/04. Previsão de recebimento em 20/04."
              />
              <div className="grid grid-cols-3 gap-2 p-2 bg-amber-50/60 dark:bg-amber-950/20 rounded border border-dashed border-amber-200">
                <div>
                  <Label className="text-[10px] text-amber-700">Item Solicitado</Label>
                  <Input value={newUpdateItemSolicitado} onChange={e => setNewUpdateItemSolicitado(e.target.value)} placeholder="Ex: Fragrância Ginger" className="h-7 text-xs mt-0.5" />
                </div>
                <div>
                  <Label className="text-[10px] text-amber-700">Fornecedor</Label>
                  <Input value={newUpdateFornecedor} onChange={e => setNewUpdateFornecedor(e.target.value)} placeholder="Nome do fornecedor" className="h-7 text-xs mt-0.5" />
                </div>
                <div>
                  <Label className="text-[10px] text-amber-700">Previsão de Entrega</Label>
                  <Input type="date" value={newUpdatePrevisaoEntrega} onChange={e => setNewUpdatePrevisaoEntrega(e.target.value)} className="h-7 text-xs mt-0.5" />
                </div>
              </div>
              <div className="flex items-center justify-between flex-wrap gap-2">
                <label className="flex items-center gap-2 text-xs">
                  <Switch checked={newUpdateVisible} onCheckedChange={setNewUpdateVisible} />
                  <span>Visível para o comercial</span>
                </label>
                <div className="flex gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setShowNewUpdate(false)}>Cancelar</Button>
                  <Button size="sm" onClick={addUpdate} disabled={saving} className="gap-1.5">
                    <Send className="h-3 w-3" />
                    {saving ? "Enviando..." : "Publicar"}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {updates.length === 0 && !showNewUpdate && (
            <p className="text-xs text-muted-foreground italic text-center py-4">Nenhuma atualização ainda. Publique a primeira!</p>
          )}

          <div className="space-y-2">
            {updates.map(u => {
              const isSystemType = u.tipo === "pendencia_criada" || u.tipo === "pendencia_resolvida" || u.tipo === "status";
              return (
                <div key={u.id} className="flex gap-3 p-3 border rounded-md">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${u.tipo === "pendencia_resolvida" ? "bg-green-100 text-green-600" : u.tipo === "pendencia_criada" ? "bg-amber-100 text-amber-600" : "bg-blue-100 text-blue-600"}`}>
                    {u.tipo === "pendencia_resolvida" ? <CheckCircle2 className="h-4 w-4" /> : u.tipo === "pendencia_criada" ? <Hourglass className="h-4 w-4" /> : <MessageSquare className="h-4 w-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium">{u.user_name || "Usuário"}</span>
                      <span className="text-xs text-muted-foreground">{new Date(u.created_at).toLocaleString("pt-BR")}</span>
                      {!u.visivel_comercial && (
                        <Badge variant="outline" className="text-[9px]">interno</Badge>
                      )}
                      {isSystemType && (
                        <Badge variant="outline" className="text-[9px] bg-muted">sistema</Badge>
                      )}
                    </div>
                    <p className="text-sm mt-1 whitespace-pre-wrap">{u.mensagem}</p>
                    {u.item_solicitado && (
                      <div className="mt-1.5 flex items-center gap-2 flex-wrap">
                        <Badge className="bg-amber-500/10 text-amber-700 border-amber-300 text-[10px] gap-1">
                          <Package className="h-2.5 w-2.5" /> {u.item_solicitado}
                        </Badge>
                        {u.fornecedor && <span className="text-[10px] text-muted-foreground">{u.fornecedor}</span>}
                        {u.previsao_entrega && (
                          <Badge variant="outline" className="text-[10px] gap-1">
                            <Clock className="h-2.5 w-2.5" /> {new Date(u.previsao_entrega).toLocaleDateString("pt-BR")}
                          </Badge>
                        )}
                        {u.recebido ? (
                          <Badge className="bg-green-500/10 text-green-700 border-green-300 text-[10px] gap-1">
                            <CheckCircle2 className="h-2.5 w-2.5" /> Recebido em {u.recebido_em ? new Date(u.recebido_em).toLocaleDateString("pt-BR") : ""}
                          </Badge>
                        ) : canEdit && (
                          <Button size="sm" variant="outline" className="h-6 text-[10px] gap-1 border-green-300 text-green-700 hover:bg-green-50" onClick={() => markUpdateReceived(u.id)}>
                            <CheckCircle2 className="h-3 w-3" /> Marcar recebido
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                  {canEdit && !isSystemType && (
                    <Button size="icon" variant="ghost" className="h-6 w-6 shrink-0" onClick={() => deleteUpdate(u.id)}>
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}


/* ============ LIVE DOCUMENTS TAB (FT/EPA versionados) ============ */

const LIVE_DOC_STATUS_CONFIG = {
  em_revisao: { label: "Em revisão", className: "bg-amber-500/10 text-amber-700 border-amber-300" },
  aprovado: { label: "Aprovado · vigente", className: "bg-emerald-500/10 text-emerald-700 border-emerald-300" },
  reprovado: { label: "Reprovado", className: "bg-red-500/10 text-red-600 border-red-300" },
  substituido: { label: "Substituído", className: "bg-muted text-muted-foreground border-border" },
};

const FIELD_LABELS = {
  briefing: "Briefing",
  ficha_tecnica: "Ficha técnica",
  bom_bulk_formula: "BOM bulk / fórmula",
  bom_embalagem_primaria: "BOM embalagem primária",
  especificacoes_produto_acabado: "Especificações do produto acabado",
  especificacoes_embalagem: "Especificações de embalagem",
  ordem_adicao: "Ordem de adição",
  parametros_in_process: "Parâmetros in-process",
  modo_preparo: "Modo de preparo",
  identificacao: "Identificação",
  identificacao_produto: "Identificação do produto",
  composicao_completa: "Composição completa",
  rendimento_teorico: "Rendimento teórico",
  observacoes_tecnicas: "Observações técnicas",
  informacoes_rotulo: "Informações de rótulo",
  kickoff: "Kickoff",
  aprovacao_cliente: "Aprovação do cliente",
  criterios_liberacao_lote: "Critérios de liberação de lote",
};

function fieldLabel(key) {
  if (!key) return "";
  return FIELD_LABELS[key] || key.replace(/_/g, " ");
}

function LiveDocumentsTab({ reqId, req }) {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  const isReviewer = ["admin", "lider_pd", "qa", "engenharia_produto", "formulador", "gestor"].includes(role);

  const [docType, setDocType] = useState("ficha_tecnica");
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffData, setDiffData] = useState(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [actingTaskId, setActingTaskId] = useState(null);
  const [generating, setGenerating] = useState(false);

  const fetchVersions = useCallback(async () => {
    if (!reqId) return;
    setLoading(true);
    try {
      const { data } = await api.get(`/pd/requests/${reqId}/live-documents/${docType}/versions`);
      setVersions(Array.isArray(data) ? data : []);
    } catch (err) {
      const detail = formatApiError(err) || "Erro ao carregar versões";
      if (err?.response?.status !== 404) toast.error(detail);
      setVersions([]);
    } finally {
      setLoading(false);
    }
  }, [reqId, docType]);

  useEffect(() => { fetchVersions(); }, [fetchVersions]);

  const openDiff = async (versionId) => {
    setDiffOpen(true);
    setDiffData(null);
    setDiffLoading(true);
    try {
      const { data } = await api.get(`/pd/document-versions/${versionId}/diff`);
      setDiffData(data);
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao carregar diff");
    } finally {
      setDiffLoading(false);
    }
  };

  const decideTask = async (taskId, decision) => {
    let comment = "";
    if (decision === "rejected") {
      comment = window.prompt("Justifique a reprovação (obrigatório):", "");
      if (!comment || !comment.trim()) {
        toast.error("Justificativa obrigatória para reprovação.");
        return;
      }
    } else {
      comment = window.prompt("Comentário (opcional):", "") || "";
    }
    setActingTaskId(taskId);
    try {
      await api.put(`/workflow/tasks/${taskId}/decision`, { decision, comment });
      toast.success(decision === "approved" ? "Tarefa aprovada" : "Tarefa reprovada");
      await fetchVersions();
      if (diffData?.current?.id) {
        const { data } = await api.get(`/pd/document-versions/${diffData.current.id}/diff`);
        setDiffData(data);
      }
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao registrar decisão");
    } finally {
      setActingTaskId(null);
    }
  };

  const generateNow = async () => {
    const reason = window.prompt("Motivo da nova versão (curto):", "Geração manual");
    if (!reason) return;
    setGenerating(true);
    try {
      await api.post(`/pd/requests/${reqId}/live-documents/${docType}/generate`, {
        reason,
        changed_fields: [docType],
      });
      toast.success("Nova versão gerada");
      await fetchVersions();
    } catch (err) {
      toast.error(formatApiError(err) || "Não foi possível gerar a versão");
    } finally {
      setGenerating(false);
    }
  };

  const docLabel = docType === "ficha_tecnica" ? "Ficha Técnica" : "EPA";

  return (
    <div className="space-y-5" data-testid="live-docs-tab">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-emerald-600" />
                Documentos Vivos — versionamento + aprovação
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                Cada alteração em dado-fonte gera uma nova versão e cria tarefas de aprovação.
                Apenas a versão <span className="font-medium text-emerald-700">aprovada</span> é vigente para produção.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <div className="inline-flex rounded-md border border-border bg-card overflow-hidden">
                <button
                  type="button"
                  onClick={() => setDocType("ficha_tecnica")}
                  data-testid="live-docs-toggle-ft"
                  className={`px-3 py-1.5 text-xs font-medium ${docType === "ficha_tecnica" ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
                >
                  Ficha Técnica
                </button>
                <button
                  type="button"
                  onClick={() => setDocType("epa")}
                  data-testid="live-docs-toggle-epa"
                  className={`px-3 py-1.5 text-xs font-medium border-l border-border ${docType === "epa" ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
                >
                  EPA
                </button>
              </div>
              {isReviewer && (
                <Button size="sm" variant="outline" onClick={generateNow} disabled={generating} data-testid="live-docs-generate-btn" className="gap-1.5">
                  {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                  Gerar versão
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={fetchVersions} disabled={loading} data-testid="live-docs-refresh-btn">
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {loading ? (
            <div className="py-10 flex items-center justify-center text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : versions.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground" data-testid="live-docs-empty">
              <FileText className="h-10 w-10 mx-auto mb-3 text-muted-foreground/30" />
              Nenhuma versão de {docLabel} disponível ainda.<br />
              {docType === "ficha_tecnica"
                ? "Disponível após aprovação do cliente e fórmula registrada."
                : "Disponível após kickoff, aprovação do cliente e fórmula registrada."}
            </div>
          ) : (
            <div className="space-y-2">
              {versions.map((v) => {
                const cfg = LIVE_DOC_STATUS_CONFIG[v.status] || LIVE_DOC_STATUS_CONFIG.em_revisao;
                const isActive = v.active_for_operation && v.status === "aprovado";
                return (
                  <div
                    key={v.id}
                    data-testid={`live-doc-version-${v.version_code}`}
                    className={`rounded-lg border ${isActive ? "border-emerald-300 bg-emerald-500/5" : "border-border bg-card"} p-3 flex items-start gap-3`}
                  >
                    <div className="shrink-0 mt-0.5">
                      <div className={`h-9 w-9 rounded-md flex items-center justify-center ${isActive ? "bg-emerald-600 text-white" : "bg-muted text-foreground"}`}>
                        <FileText className="h-4 w-4" />
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-sm">{v.version_code || `v${v.version_number}`}</span>
                        <Badge variant="outline" className={`text-[10px] ${cfg.className}`}>{cfg.label}</Badge>
                        {isActive && <Badge variant="outline" className="text-[10px] bg-emerald-500/10 text-emerald-700 border-emerald-300">VIGENTE</Badge>}
                        {v.source_trigger && v.source_trigger !== "manual" && (
                          <Badge variant="outline" className="text-[10px]">auto · {v.source_trigger}</Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-1 truncate">
                        {v.reason || "(sem motivo)"} · por {v.created_by_name || "—"} · {v.created_at?.replace("T", " ").slice(0, 16)}
                      </p>
                      {Array.isArray(v.changed_fields) && v.changed_fields.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {v.changed_fields.slice(0, 6).map((f) => (
                            <Badge key={f} variant="outline" className="text-[10px] bg-amber-500/5 text-amber-700 border-amber-200">
                              {fieldLabel(f)}
                            </Badge>
                          ))}
                          {v.changed_fields.length > 6 && (
                            <Badge variant="outline" className="text-[10px]">+{v.changed_fields.length - 6}</Badge>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="shrink-0 flex flex-col items-end gap-1.5">
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-1.5 h-7 text-xs"
                        onClick={() => openDiff(v.id)}
                        data-testid={`live-doc-view-${v.version_code}`}
                      >
                        <Eye className="h-3 w-3" /> Ver diff
                      </Button>
                      <a
                        href={`${BACKEND_URL}/api/pd/document-versions/${v.id}/pdf`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-1"
                        data-testid={`live-doc-pdf-${v.version_code}`}
                      >
                        <Download className="h-3 w-3" /> PDF
                      </a>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={diffOpen} onOpenChange={setDiffOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto" data-testid="live-doc-diff-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
              Diff & aprovação — {diffData?.current?.version_code || "..."}
            </DialogTitle>
            <DialogDescription>
              {diffData?.previous
                ? `Comparando com ${diffData.previous.version_code}`
                : "Primeira versão (sem versão anterior)"}
            </DialogDescription>
          </DialogHeader>

          {diffLoading || !diffData ? (
            <div className="py-12 flex items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-4">
              {Array.isArray(diffData.current?.source_changes) && diffData.current.source_changes.length > 0 && (
                <div className="rounded-md border border-border bg-amber-500/5 p-3">
                  <div className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1.5">
                    <AlertTriangle className="h-3.5 w-3.5" /> Mudanças no dado-fonte que dispararam esta versão
                  </div>
                  <div className="space-y-1 text-xs">
                    {diffData.current.source_changes.map((c, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="font-medium min-w-[140px]">{c.label || c.field}:</span>
                        <span className="text-muted-foreground line-through">{String(c.before ?? "—")}</span>
                        <ArrowRight className="h-3 w-3 mt-0.5 text-muted-foreground" />
                        <span className="text-foreground font-medium">{String(c.after ?? "—")}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                  Diferenças campo a campo ({diffData.differences?.length || 0})
                </h4>
                {(!diffData.differences || diffData.differences.length === 0) ? (
                  <p className="text-xs text-muted-foreground italic">Sem diferenças detectadas no snapshot.</p>
                ) : (
                  <div className="space-y-1.5 max-h-[260px] overflow-y-auto pr-1">
                    {diffData.differences.map((d, i) => (
                      <div key={i} className="rounded border border-border p-2 text-xs">
                        <div className="font-medium mb-1">{d.label || d.path}</div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="rounded bg-red-500/5 border border-red-200 px-2 py-1 break-all">
                            <div className="text-[10px] uppercase text-red-600/70 mb-0.5">Antes</div>
                            <div className="text-foreground">{String(d.before ?? "—")}</div>
                          </div>
                          <div className="rounded bg-emerald-500/5 border border-emerald-200 px-2 py-1 break-all">
                            <div className="text-[10px] uppercase text-emerald-700/70 mb-0.5">Depois</div>
                            <div className="text-foreground">{String(d.after ?? "—")}</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                  Tarefas de aprovação
                </h4>
                {(!diffData.approval_tasks || diffData.approval_tasks.length === 0) ? (
                  <p className="text-xs text-muted-foreground italic">Nenhuma tarefa de aprovação vinculada.</p>
                ) : (
                  <div className="space-y-1.5">
                    {diffData.approval_tasks.map((t) => {
                      const isClosed = t.status === "concluida" || t.status === "cancelada";
                      const decisionBadge =
                        t.decision === "approved"
                          ? "bg-emerald-500/10 text-emerald-700 border-emerald-300"
                          : t.decision === "rejected"
                            ? "bg-red-500/10 text-red-600 border-red-300"
                            : "bg-amber-500/10 text-amber-700 border-amber-300";
                      const isMine = t.responsible_id === user?.id;
                      const canDecide = !isClosed && (isMine || role === "admin" || role === "gestor" || role === "lider_pd");
                      return (
                        <div key={t.id} className="rounded border border-border p-2 text-xs flex items-start gap-2" data-testid={`approval-task-${t.id}`}>
                          <div className="flex-1 min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-medium">{t.title}</span>
                              <Badge variant="outline" className={`text-[10px] ${decisionBadge}`}>
                                {t.decision === "approved" ? "Aprovada" : t.decision === "rejected" ? "Reprovada" : t.status}
                              </Badge>
                            </div>
                            <div className="text-muted-foreground mt-0.5">
                              Resp.: {t.responsible_name || "—"} · prazo {t.due_date?.slice(0, 10) || "—"}
                              {t.decision_comment && (
                                <span className="block mt-0.5 italic">"{t.decision_comment}"</span>
                              )}
                            </div>
                          </div>
                          {canDecide && (
                            <div className="flex flex-col gap-1 shrink-0">
                              <Button
                                size="sm"
                                variant="default"
                                className="h-7 px-2 gap-1 text-xs bg-emerald-600 hover:bg-emerald-700"
                                onClick={() => decideTask(t.id, "approved")}
                                disabled={actingTaskId === t.id}
                                data-testid={`approval-task-${t.id}-approve`}
                              >
                                <ThumbsUp className="h-3 w-3" /> Aprovar
                              </Button>
                              <Button
                                size="sm"
                                variant="destructive"
                                className="h-7 px-2 gap-1 text-xs"
                                onClick={() => decideTask(t.id, "rejected")}
                                disabled={actingTaskId === t.id}
                                data-testid={`approval-task-${t.id}-reject`}
                              >
                                <ThumbsDown className="h-3 w-3" /> Reprovar
                              </Button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setDiffOpen(false)} data-testid="live-doc-diff-close">Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
