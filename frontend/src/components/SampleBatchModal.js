import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, Trash2, ChevronDown, ChevronUp, X } from "lucide-react";
import { FieldHint } from "@/components/ui/FieldHint";
import {
    DEFAULT_PRICE_DISPLAY,
    DEFAULT_VOLUME_DISPLAY,
    fmtPriceDisplay,
    fmtVolumeDisplay,
    seedPriceDisplay,
    seedVolumeDisplay,
} from "@/lib/masks";
import { CurrencyInput } from "@/components/ui/CurrencyInput";

function formatSlugLabel(value) {
    if (!value) return "";
    return String(value)
        .split("_")
        .map((part) => part ? part[0].toUpperCase() + part.slice(1) : "")
        .join(" ");
}

export default function SampleBatchModal({
    open,
    onOpenChange,
    batchSamples,
    setBatchSamples,
    projetoData,
    onProjetoDataChange,
    onSubmit,
    addVariacao,
    removeVariacao,
    updateVariacao,
    generateVariacaoLetters,
    constants,
    onAddSample,
}) {
    const [projetoExpanded, setProjetoExpanded] = useState(true);
    const [restricaoInput, setRestricaoInput] = useState("");

    const sampleTypes = constants?.sample_tipos || [];
    const variationParams = constants?.sample_parametros_variacao || [];
    // A4/A5: mesma fonte de verdade do CRM (categoria_interesse / project_tipo_servico) —
    // sem input livre divergente.
    const categoriaOptions = Array.from(new Map(
        Object.entries(constants?.categoria_interesse || {}).flatMap(([group, values]) =>
            (values || []).map((value) => [value, { value, group, label: formatSlugLabel(value) }])
        )
    ).values());
    const tipoServicoOptions = constants?.project_tipo_servico || [];

    const updateSample = (index, field, value) => {
        const next = [...batchSamples];
        next[index] = { ...next[index], [field]: value };
        setBatchSamples(next);
    };

    const updateProjeto = (field, value) => {
        onProjetoDataChange?.({ ...projetoData, [field]: value });
    };

    const addRestricao = (texto) => {
        const trimmed = texto.trim();
        if (!trimmed) return;
        const atual = projetoData?.restricoes_tecnicas || [];
        if (!atual.includes(trimmed)) {
            updateProjeto("restricoes_tecnicas", [...atual, trimmed]);
        }
        setRestricaoInput("");
    };

    const removeRestricao = (index) => {
        const atual = projetoData?.restricoes_tecnicas || [];
        updateProjeto("restricoes_tecnicas", atual.filter((_, i) => i !== index));
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-5xl max-h-[92vh] flex flex-col p-0 overflow-hidden">
                <DialogHeader className="p-6 pb-3 border-b bg-gradient-to-r from-primary/5 to-primary/10">
                    <DialogTitle className="font-heading text-2xl">Criar Amostras em Lote</DialogTitle>
                    <DialogDescription className="text-sm text-muted-foreground">
                        Cada amostra recebe numeração global e pode gerar variações independentes.
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4">
                    <div className="space-y-6">

                        {/* R02: Dados do Projeto */}
                        {projetoData && (
                            <div className="rounded-2xl border border-violet-200 bg-violet-50/50 overflow-hidden">
                                <button
                                    type="button"
                                    className="w-full flex items-center justify-between px-5 py-3 text-left"
                                    onClick={() => setProjetoExpanded(!projetoExpanded)}
                                >
                                    <div>
                                        <span className="text-sm font-semibold text-violet-800">Dados do Projeto</span>
                                        {projetoData.nome_projeto && (
                                            <span className="ml-2 text-xs text-violet-600">{projetoData.nome_projeto}</span>
                                        )}
                                    </div>
                                    {projetoExpanded
                                        ? <ChevronUp className="h-4 w-4 text-violet-600" />
                                        : <ChevronDown className="h-4 w-4 text-violet-600" />
                                    }
                                </button>

                                {projetoExpanded && (
                                    <div className="px-5 pb-5 space-y-4 border-t border-violet-200">
                                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 pt-4">
                                            <div className="space-y-2 md:col-span-2">
                                                <Label className="text-violet-700">Nome do projeto</Label>
                                                <Input
                                                    readOnly
                                                    value={projetoData.nome_projeto || ""}
                                                    className="bg-violet-50 border-violet-200 cursor-default"
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <Label className="text-violet-700">Categoria</Label>
                                                <Select value={projetoData.categoria || ""} onValueChange={(value) => updateProjeto("categoria", value)}>
                                                    <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                                    <SelectContent>
                                                        {categoriaOptions.map((option) => (
                                                            <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                                                        ))}
                                                    </SelectContent>
                                                </Select>
                                            </div>
                                            <div className="space-y-2">
                                                <Label className="text-violet-700">Responsável comercial</Label>
                                                <Input
                                                    value={projetoData.responsavel_comercial || ""}
                                                    onChange={(e) => updateProjeto("responsavel_comercial", e.target.value)}
                                                    placeholder="Nome do responsável"
                                                />
                                            </div>
                                            <div className="space-y-2 md:col-span-2">
                                                <Label className="text-violet-700">Ideia / conceito</Label>
                                                <Textarea
                                                    rows={2}
                                                    value={projetoData.ideia_conceito || ""}
                                                    onChange={(e) => updateProjeto("ideia_conceito", e.target.value)}
                                                    placeholder="Descreva o conceito do produto"
                                                />
                                            </div>
                                            <div className="space-y-2 md:col-span-2">
                                                <Label className="text-violet-700">Referência de mercado</Label>
                                                <Textarea
                                                    rows={2}
                                                    value={projetoData.referencia_mercado || ""}
                                                    onChange={(e) => updateProjeto("referencia_mercado", e.target.value)}
                                                    placeholder="Concorrentes, inspirações, benchmarks"
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <Label className="text-violet-700">Público-alvo</Label>
                                                <Input
                                                    value={projetoData.publico_alvo || ""}
                                                    onChange={(e) => updateProjeto("publico_alvo", e.target.value)}
                                                    placeholder="Ex: Mulheres 25-45 anos"
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <Label className="text-violet-700">Posicionamento</Label>
                                                <Input
                                                    value={projetoData.posicionamento || ""}
                                                    onChange={(e) => updateProjeto("posicionamento", e.target.value)}
                                                    placeholder="Premium, masstige, popular..."
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <Label className="text-violet-700">Tipo de serviço</Label>
                                                <Select value={projetoData.tipo_servico || ""} onValueChange={(value) => updateProjeto("tipo_servico", value)}>
                                                    <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                                    <SelectContent>
                                                        {tipoServicoOptions.map((option) => (
                                                            <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                        ))}
                                                    </SelectContent>
                                                </Select>
                                            </div>
                                            <div className="space-y-2">
                                                <Label className="text-violet-700">Prazo desejado</Label>
                                                <Input
                                                    type="date"
                                                    value={projetoData.prazo_desejado_amostra || ""}
                                                    onChange={(e) => updateProjeto("prazo_desejado_amostra", e.target.value)}
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <Label className="text-violet-700">Faixa de preço (R$)</Label>
                                                <Input
                                                    type="text"
                                                    inputMode="decimal"
                                                    value={projetoData.faixa_preco_venda ?? ""}
                                                    onChange={(e) => updateProjeto("faixa_preco_venda", e.target.value)}
                                                    onFocus={() => updateProjeto("faixa_preco_venda", seedPriceDisplay(projetoData.faixa_preco_venda))}
                                                    onBlur={(e) => updateProjeto("faixa_preco_venda", fmtPriceDisplay(e.target.value))}
                                                    placeholder={DEFAULT_PRICE_DISPLAY}
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <Label className="text-violet-700">Volume estimado / pedido</Label>
                                                <Input
                                                    type="text"
                                                    inputMode="numeric"
                                                    value={projetoData.volume_estimado_pedido ?? ""}
                                                    onChange={(e) => updateProjeto("volume_estimado_pedido", e.target.value)}
                                                    onFocus={() => updateProjeto("volume_estimado_pedido", seedVolumeDisplay(projetoData.volume_estimado_pedido))}
                                                    onBlur={(e) => updateProjeto("volume_estimado_pedido", fmtVolumeDisplay(e.target.value))}
                                                    placeholder={DEFAULT_VOLUME_DISPLAY}
                                                />
                                            </div>
                                            <div className="space-y-2 md:col-span-2">
                                                <Label className="text-violet-700">Sensorial desejado</Label>
                                                <Textarea
                                                    rows={2}
                                                    value={projetoData.sensorial_desejado || ""}
                                                    onChange={(e) => updateProjeto("sensorial_desejado", e.target.value)}
                                                    placeholder="Textura, espalhabilidade, acabamento, fragrância..."
                                                />
                                            </div>
                                            <div className="space-y-2 md:col-span-2">
                                                <Label className="text-violet-700">Claims desejados</Label>
                                                <Textarea
                                                    rows={2}
                                                    value={projetoData.claims_desejados || ""}
                                                    onChange={(e) => updateProjeto("claims_desejados", e.target.value)}
                                                    placeholder="Hidratante 72h, sem sulfato, vegano..."
                                                />
                                            </div>
                                            <div className="space-y-2 md:col-span-2">
                                                <Label className="text-violet-700">Restrições técnicas</Label>
                                                <div className="flex gap-2">
                                                    <Input
                                                        value={restricaoInput}
                                                        onChange={(e) => setRestricaoInput(e.target.value)}
                                                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addRestricao(restricaoInput); } }}
                                                        placeholder="Digite e pressione Enter"
                                                    />
                                                    <Button
                                                        type="button"
                                                        variant="outline"
                                                        size="sm"
                                                        onClick={() => addRestricao(restricaoInput)}
                                                    >
                                                        <Plus className="h-4 w-4" />
                                                    </Button>
                                                </div>
                                                {(projetoData.restricoes_tecnicas || []).length > 0 && (
                                                    <div className="flex flex-wrap gap-1.5 mt-2">
                                                        {(projetoData.restricoes_tecnicas || []).map((r, i) => (
                                                            <Badge key={i} variant="secondary" className="gap-1 text-xs">
                                                                {r}
                                                                <button type="button" onClick={() => removeRestricao(i)}>
                                                                    <X className="h-3 w-3" />
                                                                </button>
                                                            </Badge>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                            <div className="space-y-2 md:col-span-2">
                                                <Label className="text-violet-700">Observações</Label>
                                                <Textarea
                                                    rows={2}
                                                    value={projetoData.observacoes_livres || ""}
                                                    onChange={(e) => updateProjeto("observacoes_livres", e.target.value)}
                                                    placeholder="Observações gerais do projeto"
                                                />
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {batchSamples.map((sample, sampleIndex) => (
                            <div key={sampleIndex} className="rounded-2xl border border-border bg-card p-5 space-y-5">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h3 className="text-lg font-semibold">Amostra {sampleIndex + 1}</h3>
                                        <p className="text-xs text-muted-foreground">
                                            {sample.variacoes?.length || 0} variação(ões)
                                        </p>
                                    </div>
                                    {batchSamples.length > 1 && (
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setBatchSamples(batchSamples.filter((_, index) => index !== sampleIndex))}
                                        >
                                            <Trash2 className="h-4 w-4 text-red-500" />
                                        </Button>
                                    )}
                                </div>

                                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                    <div className="space-y-2 md:col-span-2">
                                        <Label>Nome do produto *</Label>
                                        <Input
                                            placeholder="Ex: Body Splash 300ml"
                                            value={sample.nome_produto || ""}
                                            onChange={(event) => updateSample(sampleIndex, "nome_produto", event.target.value)}
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Tipo de amostra *</Label>
                                        <Select
                                            value={sample.tipo_amostra || ""}
                                            onValueChange={(value) => updateSample(sampleIndex, "tipo_amostra", value)}
                                        >
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                {sampleTypes.map((option) => (
                                                    <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label><FieldHint hint="Define o critério que diferencia cada variação de amostra: fragrância, cor, concentração, etc.">Parâmetro de variação</FieldHint></Label>
                                        <Select
                                            value={sample.parametro_variacao || "nenhuma"}
                                            onValueChange={(value) => updateSample(sampleIndex, "parametro_variacao", value === "nenhuma" ? "" : value)}
                                        >
                                            <SelectTrigger><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="nenhuma">Nenhuma</SelectItem>
                                                {variationParams.map((option) => (
                                                    <SelectItem key={option} value={option}>{formatSlugLabel(option)}</SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Prazo de entrega ao cliente *</Label>
                                        <Input
                                            type="date"
                                            value={sample.prazo_entrega_cliente || ""}
                                            onChange={(event) => updateSample(sampleIndex, "prazo_entrega_cliente", event.target.value)}
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>
                                            Referência de fórmula
                                            {sample.tipo_amostra === "adaptacao_de_formula" && <span className="text-destructive"> *</span>}
                                        </Label>
                                        <Input
                                            placeholder="Obrigatória em adaptação"
                                            value={sample.referencia_formula || ""}
                                            onChange={(event) => updateSample(sampleIndex, "referencia_formula", event.target.value)}
                                            className={sample.tipo_amostra === "adaptacao_de_formula" && !String(sample.referencia_formula || "").trim() ? "border-destructive" : ""}
                                        />
                                    </div>
                                    <div className="space-y-2 md:col-span-2">
                                        <Label>Briefing base</Label>
                                        <Textarea
                                            rows={3}
                                            value={sample.briefing_base || ""}
                                            onChange={(event) => updateSample(sampleIndex, "briefing_base", event.target.value)}
                                        />
                                    </div>
                                    <div className="space-y-2 md:col-span-2">
                                        <Label>Briefing específico da amostra</Label>
                                        <Textarea
                                            rows={3}
                                            value={sample.briefing_especifico || ""}
                                            onChange={(event) => updateSample(sampleIndex, "briefing_especifico", event.target.value)}
                                        />
                                    </div>
                                </div>

                                <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 space-y-4">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h4 className="text-sm font-semibold text-emerald-700">Variações</h4>
                                            <p className="text-xs text-emerald-700/80">
                                                Códigos previstos: {generateVariacaoLetters(sample.variacoes?.length || 0).map((letter) => `/${letter}`).join(" ")}
                                            </p>
                                        </div>
                                        <Button variant="outline" size="sm" onClick={() => addVariacao(sampleIndex)}>
                                            <Plus className="h-3.5 w-3.5 mr-1" /> Adicionar variação
                                        </Button>
                                    </div>

                                    <div className="space-y-3">
                                        {(sample.variacoes || []).map((variacao, variacaoIndex) => (
                                            <div key={variacaoIndex} className="rounded-lg border border-emerald-200 bg-background p-3 space-y-3">
                                                <div className="flex items-center justify-between">
                                                    <span className="text-xs font-semibold text-emerald-700">
                                                        Variação {generateVariacaoLetters(sample.variacoes.length)[variacaoIndex]}
                                                    </span>
                                                    {sample.variacoes.length > 1 && (
                                                        <Button variant="ghost" size="sm" onClick={() => removeVariacao(sampleIndex, variacaoIndex)}>
                                                            <Trash2 className="h-3.5 w-3.5 text-red-500" />
                                                        </Button>
                                                    )}
                                                </div>
                                                <Input
                                                    placeholder="Descrição da variação"
                                                    value={variacao.descricao_aplicacao || ""}
                                                    onChange={(event) => updateVariacao(sampleIndex, variacaoIndex, "descricao_aplicacao", event.target.value)}
                                                />
                                                <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                                                    <Input
                                                        type="number"
                                                        placeholder="% fragrância"
                                                        value={variacao.percentual_fragrancia || ""}
                                                        onChange={(event) => updateVariacao(sampleIndex, variacaoIndex, "percentual_fragrancia", event.target.value)}
                                                    />
                                                    <Input
                                                        placeholder="Ref. fragrância"
                                                        value={variacao.referencia_fragrancia || ""}
                                                        onChange={(event) => updateVariacao(sampleIndex, variacaoIndex, "referencia_fragrancia", event.target.value)}
                                                    />
                                                    <CurrencyInput
                                                        value={variacao.custo_fragrancia || ""}
                                                        currency={variacao.custo_fragrancia_currency || "USD"}
                                                        onValueChange={(value) => updateVariacao(sampleIndex, variacaoIndex, "custo_fragrancia", value)}
                                                        onCurrencyChange={(currency) => updateVariacao(sampleIndex, variacaoIndex, "custo_fragrancia_currency", currency)}
                                                        showHint={false}
                                                        size="sm"
                                                    />
                                                </div>
                                                <Textarea
                                                    rows={2}
                                                    placeholder="Observações específicas"
                                                    value={variacao.observacoes_especificas || ""}
                                                    onChange={(event) => updateVariacao(sampleIndex, variacaoIndex, "observacoes_especificas", event.target.value)}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>

                    <Button variant="outline" className="w-full mt-6" onClick={() => onAddSample ? onAddSample() : setBatchSamples([...batchSamples, {
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
                    }])}>
                        <Plus className="h-4 w-4 mr-2" /> Adicionar Outra Amostra
                    </Button>
                </div>

                <DialogFooter className="p-6 pt-3 border-t">
                    <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
                    <Button onClick={onSubmit}>
                        Criar {batchSamples.filter((sample) => sample.nome_produto?.trim()).length} amostra(s)
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
