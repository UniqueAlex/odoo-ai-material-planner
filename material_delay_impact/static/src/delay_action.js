/** @odoo-module **/

import * as owlApi from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { useSetupAction } from "@web/search/action_hook";
import { ReallocationPanel } from "./reallocation_panel";

const { Component, onWillStart, onMounted, onWillUnmount } = owlApi;
const useState = owlApi.useState || owlApi.proxy;

const { DateTime } = luxon;
// Reports remain in this tab's memory. Only input values and an opaque token
// enter Odoo history state; raw business reports are never put in the URL or
// persistent browser storage. A full reload requires a fresh analysis.
const navigationReports = new Map();
let nextReportToken = 0;
const MAX_NAVIGATION_REPORTS = 8;
const COPY = {
    zh: {
        title: "采购延期影响分析", back: "返回采购单", line: "采购明细",
        arrival: "假设到货时间", timezone: "时区", analyze: "分析影响", running: "正在读取并计算…",
        intro: "输入未收货部分的假设到货时间，查看制造需求的材料缺口变化。",
        readonly: "只读分析：假设日期用于本次计算，采购单、库存和预留不会因分析改变。",
        loading: "正在读取采购明细…", select: "请选择", pending: "未收", company: "公司", warehouse: "仓库",
        material: "物料", stock: "在库", reserved: "已预留", result: "分析结果", need: "需求时间", mo: "制造单",
        baseline: "原计划：用料时缺料", delayed: "延期后：用料时缺料", added: "延期造成的额外缺料", finalMissing: "全部已知到货后仍缺", full: "按假设到货全部补齐时间",
        shortageHelp: "前两列比较同一个用料时间，延期造成的额外缺料为两者差额。剩余缺料按全部已知供给到位后计算。数量单位：{unit}。",
        change: "变化", evidence: "查看供需依据", quantity: "数量", source: "来源", time: "时间",
        snapshot: "读取时间", unit: "单位", surplus: "已知事件后的剩余库存", unknown: "已知供给不足",
        scope: "报告只评估该原材料在需求时点的覆盖情况；材料补足时间不代表制造单完工时间。",
        empty: "当前范围内没有有效制造需求。", detail: "分配依据", currentStock: "当前库存",
        new_shortage: "新增缺料", worsened_shortage: "已有缺料加重", improved_shortage: "缺口减少",
        later_fulfillment: "补足更晚", existing_shortage_unchanged: "已有缺料未变", no_new_risk: "无新增缺口",
        invalid: "请选择明细，并输入有效的日期、时间和时区。", failed: "分析未完成，请检查输入后重试。",
        missingOrder: "页面缺少采购单信息，请返回采购单并重新打开延期分析。",
        previousResult: "已恢复上次分析结果，数据截至下方读取时间。点击「分析影响」可读取最新数据并重新计算。",
    },
    en: {
        title: "Purchase delay impact", back: "Back to purchase order", line: "Purchase line",
        arrival: "Assumed arrival", timezone: "Time zone", analyze: "Analyze impact", running: "Reading and calculating…",
        intro: "Set a later arrival for the unreceived quantity to compare material shortages for manufacturing demand.",
        readonly: "Read-only analysis: the assumed date is used in this calculation. Analysis does not change purchase, stock or reservation records.",
        loading: "Reading purchase lines…", select: "Select", pending: "Pending", company: "Company", warehouse: "Warehouse",
        material: "Material", stock: "On hand", reserved: "Reserved", result: "Analysis result", need: "Need time", mo: "Manufacturing order",
        baseline: "Short at need: original plan", delayed: "Short at need: delayed arrival", added: "Extra shortage at need due to delay", finalMissing: "Still short after all known arrivals", full: "Full material coverage with assumed arrival",
        shortageHelp: "The first two shortage columns compare the same need time. Extra shortage is their difference. The remaining shortage is calculated after all known supply arrives. Quantity unit: {unit}.",
        change: "Change", evidence: "Supply and demand evidence", quantity: "Quantity", source: "Source", time: "Time",
        snapshot: "Read at", unit: "Unit", surplus: "Unallocated stock after known events", unknown: "Known supply is insufficient",
        scope: "This report evaluates coverage of this material at the demand time. Material availability is not manufacturing completion.",
        empty: "No active manufacturing demand was found in this scope.", detail: "Allocation evidence", currentStock: "Current stock",
        new_shortage: "New shortage", worsened_shortage: "Existing shortage worsens", improved_shortage: "Shortage decreases",
        later_fulfillment: "Later fulfillment", existing_shortage_unchanged: "Existing shortage unchanged", no_new_risk: "No added shortage",
        invalid: "Select a line and enter a valid date, time and time zone.", failed: "Analysis did not complete. Check the input and retry.",
        missingOrder: "Purchase order information is missing. Return to the purchase order and reopen delay analysis.",
        previousResult: "Previous analysis restored, using data from the read time below. Click Analyze impact to read current data and recalculate.",
    },
    fr: {
        title: "Impact d’un retard d’achat", back: "Retour à la commande", line: "Ligne d’achat",
        arrival: "Arrivée supposée", timezone: "Fuseau horaire", analyze: "Analyser l’impact", running: "Lecture et calcul…",
        intro: "Indiquez une arrivée plus tardive pour la quantité non reçue et comparez les manques de matière pour la fabrication.",
        readonly: "Analyse en lecture seule : la date supposée sert au calcul. L’analyse ne modifie ni les achats, ni le stock, ni les réservations.",
        loading: "Lecture des lignes d’achat…", select: "Sélectionner", pending: "À recevoir", company: "Société", warehouse: "Entrepôt",
        material: "Matière", stock: "En stock", reserved: "Réservé", result: "Résultat", need: "Date du besoin", mo: "Ordre de fabrication",
        baseline: "Manque au besoin : plan initial", delayed: "Manque au besoin : arrivée retardée", added: "Manque supplémentaire au besoin dû au retard", finalMissing: "Manque après toutes les arrivées connues", full: "Couverture complète avec l’arrivée supposée",
        shortageHelp: "Les deux premières colonnes de manque comparent la même date de besoin. Le manque supplémentaire est leur différence. Le manque restant est calculé après tous les approvisionnements connus. Unité : {unit}.",
        change: "Évolution", evidence: "Données d’approvisionnement et de demande", quantity: "Quantité", source: "Source", time: "Date",
        snapshot: "Lecture effectuée le", unit: "Unité", surplus: "Stock non affecté après les événements connus", unknown: "Approvisionnement connu insuffisant",
        scope: "Ce rapport évalue la couverture de cette matière à la date du besoin. Sa disponibilité ne constitue pas une date de fin de fabrication.",
        empty: "Aucun besoin de fabrication actif dans ce périmètre.", detail: "Détail des affectations", currentStock: "Stock actuel",
        new_shortage: "Nouveau manque", worsened_shortage: "Manque existant aggravé", improved_shortage: "Manque réduit",
        later_fulfillment: "Disponibilité plus tardive", existing_shortage_unchanged: "Manque existant inchangé", no_new_risk: "Aucun manque ajouté",
        invalid: "Sélectionnez une ligne et saisissez une date, une heure et un fuseau valides.", failed: "L’analyse n’a pas abouti. Vérifiez les données et réessayez.",
        missingOrder: "Les informations de la commande sont absentes. Retournez à la commande et rouvrez l’analyse du retard.",
        previousResult: "Analyse précédente restaurée avec les données à la date de lecture ci-dessous. Cliquez sur Analyser l’impact pour relire les données actuelles et recalculer.",
    },
};

const AI_COPY = {
    zh: {
        ai: "AI 分析", settings: "AI 设置", close: "收起设置", provider: "服务商", model: "模型",
        key: "API 密钥", keyHelp: "首次填写或更换密钥时输入；留空保留同一服务商的现有密钥。保存后输入框清空，密钥不回显。",
        save: "保存配置", remove: "移除密钥", test: "测试连接（可能收费）", configured: "已配置", notConfigured: "尚未配置 AI",
        adminHelp: "只有 Odoo 系统管理员可以修改配置。配置按采购单所属公司保存。",
        privacy: "配置服务商并勾选下方授权后，AI 操作会发送本次物料的采购/收货、库存预留、相关在途、制造需求和计算证据；不发送价格、联系人、备注或整个数据库。真实分析及测试连接可能产生 API 费用。",
        secure: "密钥在数据库之外加密保存，仅供 Odoo 服务账户读取。模块免费；模型服务由客户自行开通和付费。迁移机器或服务账户前请阅读安装说明。",
        aiConsent: "允许本页 AI 操作将上述数据发送给所选服务商，并使用我的模型账户额度。未勾选时只进行本地计算。",
        guides: "配置指南", guideSteps: "打开服务商官方平台 → 创建该平台的 API Key → 核对 API 余额/权限 → 在这里选择服务商和模型 → 输入密钥并保存 → 测试连接 → 运行分析。聊天订阅或网页会员不代表 API 可用额度。",
        openaiGuide: "OpenAI：在开发者平台创建 API Key，确认 Responses 权限及 API 计费。独立适配已实现，当前未完成真实验收。",
        deepseekGuide: "DeepSeek：在开放平台创建 API Key 并充值 API 余额。已在本机 Odoo 19 页面验证真实调用；其他部署仍需单独核验。",
        claudeGuide: "Claude：在官方 Console 创建 API Key、配置 API 计费。后续适配，当前无法在这里选择。",
        geminiGuide: "Gemini：在 Google AI Studio 创建项目/API Key，核对模型权限及额度。后续适配，当前无法在这里选择。",
        waitingAI: "尚未进行 AI 分析。缺口计算结果仍可查看。", runAI: "运行 AI 分析（可能收费）", aiRunning: "AI 正在查阅证据并生成报告…",
        aiVerified: "明细中的数字、日期与引用已核对；AI 文字解释和建议仍需业务复核。", explanation: "影响原因", checks: "优先复核建议", limits: "分析范围与限制", reads: "已读取证据", generated: "生成时间", low: "低风险", medium: "中风险", high: "高风险",
        saved: "配置已保存。", removed: "密钥已移除。", connected: "连接成功。", aiFailed: "AI 分析未完成；缺口计算结果保留。",
        configuration: "请填写有效的服务商、模型和密钥，并保存配置。", secure_storage: "无法使用安全存储，请核对 Odoo 服务账户、依赖和私有目录权限。",
        expired: "本次证据已过期或服务重启，请点击「分析影响」重新读取。", busy: "本次 AI 分析已在运行。", admin: "需要系统管理员配置权限。",
        network: "无法连接模型服务或等待超时，请检查网络后重试。", timeout: "模型分析超时，未生成受检报告。", balance: "API 余额或额度不足，请检查所选平台账单。",
        permission: "密钥权限不足，请核对所选平台权限。", rate: "请求被限流，请稍后重试。", service: "模型服务暂时不可用，请稍后重试。", parameters: "模型或接口参数不被支持，请检查配置。",
        format: "模型报告格式不符合要求，未接受该报告。", validation: "模型数字、日期、等级或引用与证据冲突，未接受该报告。", tool: "模型读取不完整或请求了不允许的工具。", budget: "模型超过读取轮次限制。", scope_limit: "本次 AI 证据超出原型限制（20 条需求或 128 KB）；计算结果仍可查看。", keyError: "API 密钥未通过认证，请在设置中更换。", modelError: "所选模型不可用，请检查模型名称或访问权限。",
    },
    en: {
        ai: "AI analysis", settings: "AI settings", close: "Close settings", provider: "Provider", model: "Model", key: "API key",
        keyHelp: "Enter a key when first configuring or replacing it. Leave blank to keep the same provider's key. The field clears after saving; the key is never returned.",
        save: "Save configuration", remove: "Remove key", test: "Test connection (may incur charges)", configured: "Configured", notConfigured: "AI not configured",
        adminHelp: "Only Odoo system administrators can change configuration. Settings belong to the purchase order's company.",
        privacy: "After provider setup and your consent below, AI actions send this material's purchase/receipt, stock/reservation, incoming supply, manufacturing demand and calculation evidence to the selected provider. Prices, contacts, notes and the full database are excluded. Analysis and connection tests may incur API charges.",
        secure: "Credentials are encrypted outside the database for the Odoo service account. The module is free; you provide and pay for your AI account. Read the installation guide before migrating the host or service account.",
        aiConsent: "Allow AI actions on this page to send the disclosed data to my selected provider and use my API balance. Unchecked: local calculations only.",
        guides: "Setup guides", guideSteps: "Open the official platform → create its API key → check API balance/permissions → choose provider/model here → enter and save key → test connection → analyze. Chat subscriptions are separate from API access.",
        openaiGuide: "OpenAI: create a developer-platform API key with Responses permission and API billing. Adapter implemented; real acceptance remains pending.",
        deepseekGuide: "DeepSeek: create an API key and fund the API balance on its platform. Real calls have been verified on the local Odoo 19 page; other deployments need separate checks.",
        claudeGuide: "Claude: create a key and configure API billing in the official Console. Planned adapter; not selectable yet.",
        geminiGuide: "Gemini: create a project/API key in Google AI Studio; check model access and quotas. Planned adapter; not selectable yet.",
        waitingAI: "AI has not run. Calculated material shortages remain available.", runAI: "Run AI analysis (may incur charges)", aiRunning: "AI is reading evidence and generating the report…",
        aiVerified: "Structured figures, dates and citations checked; review AI explanations and recommendations.", explanation: "Reasons for impact", checks: "Priority review steps", limits: "Scope and limitations", reads: "Evidence read", generated: "Generated at", low: "Low risk", medium: "Medium risk", high: "High risk",
        saved: "Configuration saved.", removed: "Key removed.", connected: "Connection successful.", aiFailed: "AI analysis incomplete; calculated results retained.",
        configuration: "Save a valid provider, model and key.", secure_storage: "Secure storage unavailable. Check the Odoo service account, dependencies and private directory permissions.", expired: "Evidence expired or the service restarted. Analyze impact again.", busy: "AI analysis is already running.", admin: "System administrator access is required.", network: "Service unreachable or timed out; check the network.", timeout: "Analysis timed out without a validated report.", balance: "API credit or quota unavailable; check provider billing.", permission: "Check key permissions.", rate: "Rate limited. Retry later.", service: "Model service temporarily unavailable.", parameters: "Unsupported model or request parameters; check settings.", format: "Report format rejected.", validation: "Report numbers, dates, risk or citations conflict with evidence.", tool: "Incomplete or invalid tool reads.", budget: "Tool-round budget exceeded.", scope_limit: "AI prototype limit exceeded (20 demands or 128 KB); calculation remains available.", keyError: "API key rejected. Replace it in settings.", modelError: "Model unavailable; check name/access.",
    },
    fr: {
        ai: "Analyse IA", settings: "Paramètres IA", close: "Fermer les paramètres", provider: "Fournisseur", model: "Modèle", key: "Clé API",
        keyHelp: "Saisissez la clé lors de la première configuration ou de son remplacement. Laissez vide pour conserver la clé du même fournisseur. Le champ est effacé après sauvegarde ; la clé n’est jamais renvoyée.",
        save: "Enregistrer", remove: "Supprimer la clé", test: "Tester la connexion (potentiellement payant)", configured: "Configuré", notConfigured: "IA non configurée",
        adminHelp: "Seuls les administrateurs système Odoo peuvent modifier la configuration. Elle appartient à la société de la commande.",
        privacy: "Après configuration et votre autorisation ci-dessous, les actions IA transmettent les achats/réceptions, stocks/réservations, approvisionnements, besoins de fabrication et calculs de cette matière au fournisseur choisi. Prix, contacts, notes et base complète sont exclus. Les analyses et tests peuvent entraîner des frais API.",
        secure: "Clé chiffrée hors base pour le compte Odoo. Module gratuit ; compte et frais IA à votre charge. Consultez le guide avant toute migration.",
        aiConsent: "Autoriser les actions IA de cette page à transmettre les données indiquées au fournisseur choisi et à utiliser mon crédit API. Sinon : calculs locaux uniquement.",
        guides: "Guides de configuration", guideSteps: "Ouvrir la plateforme officielle → créer sa clé API → vérifier solde/droits → choisir fournisseur/modèle → saisir et enregistrer → tester → analyser. Les abonnements de chat sont distincts des API.",
        openaiGuide: "OpenAI : créer une clé sur la plateforme développeur, avec droits Responses et facturation API. Adaptateur disponible ; validation réelle encore en attente.",
        deepseekGuide: "DeepSeek : créer une clé et créditer le solde API sur sa plateforme. Les appels réels ont été vérifiés sur la page Odoo 19 locale ; les autres déploiements restent à vérifier.",
        claudeGuide: "Claude : créer une clé et configurer la facturation API dans la Console officielle. Adaptation prévue ; non sélectionnable actuellement.",
        geminiGuide: "Gemini : créer un projet/une clé dans Google AI Studio, vérifier accès et quotas. Adaptation prévue ; non sélectionnable actuellement.",
        waitingAI: "L’analyse IA n’a pas été exécutée. Les résultats calculés restent disponibles.", runAI: "Lancer l’IA (potentiellement payant)", aiRunning: "L’IA consulte les données et génère le rapport…",
        aiVerified: "Chiffres structurés, dates et références vérifiés ; explications et recommandations de l’IA à examiner.", explanation: "Causes de l’impact", checks: "Vérifications prioritaires", limits: "Périmètre et limites", reads: "Données consultées", generated: "Généré le", low: "Risque faible", medium: "Risque moyen", high: "Risque élevé",
        saved: "Configuration enregistrée.", removed: "Clé supprimée.", connected: "Connexion réussie.", aiFailed: "Analyse IA incomplète ; calculs conservés.",
        configuration: "Enregistrez un fournisseur, un modèle et une clé valides.", secure_storage: "Stockage sécurisé indisponible. Vérifiez le compte Odoo, les dépendances et les droits du répertoire privé.", expired: "Données expirées ou service redémarré. Relancez Analyser l’impact.", busy: "Analyse IA déjà en cours.", admin: "Droits d’administrateur système requis.", network: "Service inaccessible ou délai dépassé.", timeout: "Délai dépassé sans rapport validé.", balance: "Solde ou quota API insuffisant ; vérifiez la facturation.", permission: "Vérifiez les droits de la clé.", rate: "Limite de fréquence atteinte. Réessayez plus tard.", service: "Service temporairement indisponible.", parameters: "Modèle ou paramètres non pris en charge.", format: "Format du rapport refusé.", validation: "Chiffres, dates, niveau ou références en conflit avec les données.", tool: "Lectures incomplètes ou non autorisées.", budget: "Limite d’appels atteinte.", scope_limit: "Limite du prototype IA dépassée (20 besoins ou 128 Ko) ; calculs disponibles.", keyError: "Clé API refusée. Remplacez-la.", modelError: "Modèle indisponible ; vérifiez nom/droits.",
    },
};

const COMPACT_COPY = {
    zh: {focus: "关键关注", reportDetails: "查看详细原因与证据", extraChecks: "其他复核建议", too_long: "AI 报告超过简报长度限制，未接受该报告。", hours: "{n} 小时", minutes: "{n} 分钟", underMinute: "不到 1 分钟", timingCaveat: "时间差不含收货、检验等作业耗时。", focusEmpty: "当前分析范围内没有待开工制造需求。", focusCovered: "本次需求由在库材料覆盖，无需依赖新到货。", focusWindow: "{mo}：{quantity} {unit} 来自 {source}。情景到货 {arrival}，需求 {need}，相隔约 {interval}。", focusDelayed: "{mo} 在 {need} 有 {quantity} {unit} 情景缺口；按已知供给，{full} 才能补齐。", focusBlocked: "{mo} 在 {need} 有 {quantity} {unit} 情景缺口；现有供给记录无法确定补齐时间。"},
    en: {focus: "Key attention", reportDetails: "View detailed reasons and evidence", extraChecks: "Other review steps", too_long: "AI report exceeded the brief length limit and was rejected.", hours: "{n} hours", minutes: "{n} minutes", underMinute: "less than 1 minute", timingCaveat: "This date difference excludes receiving and inspection time.", focusEmpty: "No unstarted manufacturing demand in this analysis scope.", focusCovered: "Current stock covers these demands without new receipts.", focusWindow: "{mo}: {quantity} {unit} from {source}. Scenario arrival {arrival}; need {need}; about {interval} apart.", focusDelayed: "{mo} has a scenario shortage of {quantity} {unit} at {need}; known supply covers it at {full}.", focusBlocked: "{mo} has a scenario shortage of {quantity} {unit} at {need}; known supply cannot establish full coverage time."},
    fr: {focus: "Point à surveiller", reportDetails: "Voir les causes détaillées et les données", extraChecks: "Autres vérifications", too_long: "Le rapport IA dépasse la longueur du résumé et a été refusé.", hours: "{n} heures", minutes: "{n} minutes", underMinute: "moins d’une minute", timingCaveat: "Cet écart exclut le temps de réception et de contrôle.", focusEmpty: "Aucun besoin de fabrication non démarré dans ce périmètre.", focusCovered: "Le stock actuel couvre ces besoins sans nouvelle réception.", focusWindow: "{mo} : {quantity} {unit} venant de {source}. Arrivée simulée {arrival} ; besoin {need} ; écart d’environ {interval}.", focusDelayed: "{mo} : manque de {quantity} {unit} à {need} dans le scénario ; couverture par les approvisionnements connus à {full}.", focusBlocked: "{mo} : manque de {quantity} {unit} à {need} dans le scénario ; les approvisionnements connus ne permettent pas de déterminer la date de couverture."},
};

Object.assign(AI_COPY.zh,{interrupted:"本次请求中断，无法确认服务商是否已计费；系统不会自动重发。重新分析后可主动发起新请求。",expired:"本次证据已过期，请点击「分析影响」重新读取。"});
Object.assign(AI_COPY.en,{interrupted:"This request was interrupted; provider billing is uncertain. It will not be resent automatically. Recalculate before explicitly starting a new request.",expired:"This evidence has expired. Analyze impact again to read current data."});
Object.assign(AI_COPY.fr,{interrupted:"Requête interrompue ; facturation inconnue. Aucun renvoi automatique. Recalculez avant une nouvelle demande explicite.",expired:"Données expirées. Relancez l’analyse."});
const CONFIG_COPY = {
    zh: {setupTitle: "首次使用：连接你的 AI", setupIntro: "缺料计算和方案比较可直接使用。需要 AI 解读时，再完成下方配置。", setupAdmin: "请联系 Odoo 系统管理员配置本公司的 AI 服务；你仍可使用本地计算。", setupStart: "开始配置 AI", savedUntested: "已保存，尚未验证", connectionPassed: "连接通过，尚未验证分析能力", capabilityPassed: "分析能力验证通过", capability: "验证分析能力", capabilityHelp: "使用模拟数据检查工具读取和结构化输出，最多两次小请求，会消耗 API 额度。通过不代表之后每份 AI 意见都正确。", preset: "建议配置", custom: "手动填写其他模型（未验证）", customHelp: "其他模型不保证兼容。保存后请验证分析能力。", pendingSave: "配置有未保存的修改，请先保存再测试。", validationNotSaved: "测试通过，但验证状态未保存（配置可能已变更）。请检查当前配置。", saved: "已保存，尚未验证。下一步：测试连接，再验证分析能力。", connected: "连接成功。下一步：验证分析能力。", capable: "工具读取与结构化输出验证通过。现在可以运行 AI 分析。", capabilityError: "模型未通过工具读取或结构化输出检查。请切回建议模型，再核对该模型的 API 权限。", usageLabel: "本次 API 用量", unknownUsage: "未取得完整用量，实际计费以服务商账单为准", region: "服务商不支持当前 Odoo 服务器所在地区。请按服务商支持地区要求部署。", network: "Odoo 服务器无法连接模型服务。请管理员检查服务器的出站 HTTPS、DNS 或网络代理；浏览器能打开官网不代表服务器能访问 API。", keyError: "密钥认证失败。请从所选服务商的 API 控制台创建有效密钥，重新粘贴并保存；不要使用网页登录密码。", modelError: "模型不存在或当前账户无权使用。先选择建议模型，再检查 API 控制台中的模型权限。", balance: "API 余额或额度不足。请到所选服务商的账单页面充值或调整 API 限额；聊天会员不包含 API 额度。", permission: "API 访问被拒绝。请核对密钥所属项目、模型访问权限及服务商支持地区。", parameters: "该模型不接受当前请求参数。请使用建议模型；手动模型可能不兼容。", configuration: "请先选择服务商、填写模型和该平台 API Key，然后保存。换服务商时需填写对应平台的新密钥。", guideSteps: "1. 打开下方官方平台并开通 API 额度。2. 选择服务商及建议模型。3. 粘贴 API Key 并保存。4. 勾选数据授权，测试连接并验证分析能力。聊天会员不等于 API 额度。", deepseekGuide: "DeepSeek：在 API 平台创建密钥并检查余额。", openaiGuide: "OpenAI：需要可调用 Responses API 的项目密钥及 API 额度。", claudeGuide: "Claude：使用 Anthropic Console 的 API Key；目前对接官方 Messages API，不含 Bedrock。", geminiGuide: "Gemini：使用 Google AI Studio 的 API Key；目前对接 Gemini API，不含 Vertex AI。"},
    en: {setupTitle: "First use: connect your AI", setupIntro: "Shortage calculations and option comparisons work immediately. Configure AI when you want an explanation.", setupAdmin: "Ask your Odoo system administrator to configure AI for this company. Local calculations remain available.", setupStart: "Set up AI", savedUntested: "Saved, not yet tested", connectionPassed: "Connection passed; analysis capability not yet tested", capabilityPassed: "Analysis capability verified", capability: "Verify analysis capability", capabilityHelp: "Uses synthetic data to check tool reading and structured output in at most two small API requests. API charges apply. Passing does not guarantee every future AI opinion is correct.", preset: "Suggested configuration", custom: "Enter another model manually (unverified)", customHelp: "Other models may be incompatible. Save and verify analysis capability before use.", pendingSave: "Unsaved changes: save before testing.", validationNotSaved: "Test passed, but its status was not saved (configuration may have changed). Check the current settings.", saved: "Saved, not yet tested. Next: test the connection, then verify analysis capability.", connected: "Connection successful. Next: verify analysis capability.", capable: "Tool reading and structured output verified. You can now run AI analysis.", capabilityError: "Tool reading or structured output verification failed. Choose the suggested model and check its API permissions.", usageLabel: "API usage for this operation", unknownUsage: "Complete usage unavailable; consult the provider bill", region: "The provider does not support the Odoo server's region. Use a deployment region supported by that provider.", network: "The Odoo server cannot reach the model API. Ask an administrator to check outbound HTTPS, DNS or proxy settings. Browser access to the website does not prove server API access.", keyError: "API key authentication failed. Create a valid key in the selected provider's API console, paste it and save. Do not use a website password.", modelError: "Model unavailable or not enabled for this account. Select the suggested model and check model access in the API console.", balance: "API credit or quota exhausted. Top up or adjust API limits in the provider billing page. A chat subscription does not include API credits.", permission: "API access denied. Check the key's project, model permissions and supported region.", parameters: "This model rejected the request parameters. Select the suggested model; manual model entries may be incompatible.", configuration: "Select a provider and model, enter its API key, then save. Switching providers requires that provider's key.", guideSteps: "1. Open the official platform below and enable API credit. 2. Select the provider and suggested model. 3. Paste its API key and save. 4. Enable data consent, test the connection and verify analysis capability. Chat subscriptions do not include API credits.", deepseekGuide: "DeepSeek: create an API key and check your API balance.", openaiGuide: "OpenAI: use a project key with Responses API access and API credit.", claudeGuide: "Claude: use an Anthropic Console API key. Direct Messages API only; Bedrock is not included.", geminiGuide: "Gemini: use a Google AI Studio API key. Direct Gemini API only; Vertex AI is not included."},
    fr: {setupTitle: "Première utilisation : connecter votre IA", setupIntro: "Les calculs de manque et la comparaison fonctionnent immédiatement. Configurez l’IA pour obtenir une interprétation.", setupAdmin: "Demandez à l’administrateur Odoo de configurer l’IA de cette société. Les calculs restent disponibles.", setupStart: "Configurer l’IA", savedUntested: "Enregistré, pas encore testé", connectionPassed: "Connexion réussie ; capacité d’analyse non vérifiée", capabilityPassed: "Capacité d’analyse vérifiée", capability: "Vérifier la capacité d’analyse", capabilityHelp: "Vérifie les outils et la sortie structurée avec des données simulées : deux petites requêtes API au maximum, potentiellement facturées. Cela ne garantit pas la justesse de chaque avis futur.", preset: "Configuration suggérée", custom: "Saisir un autre modèle (non vérifié)", customHelp: "Compatibilité non garantie. Enregistrez puis vérifiez la capacité d’analyse.", pendingSave: "Modifications non enregistrées : enregistrez avant le test.", validationNotSaved: "Test réussi, mais état non enregistré (configuration éventuellement modifiée). Vérifiez les paramètres.", saved: "Enregistré, non vérifié. Testez la connexion puis la capacité d’analyse.", connected: "Connexion réussie. Vérifiez maintenant la capacité d’analyse.", capable: "Outils et sortie structurée vérifiés. Vous pouvez lancer l’analyse IA.", capabilityError: "Échec de vérification des outils ou du format. Choisissez le modèle suggéré et vérifiez ses permissions API.", usageLabel: "Consommation API de cette opération", unknownUsage: "Consommation complète inconnue ; consultez la facture du fournisseur", region: "Région du serveur Odoo non prise en charge par ce fournisseur.", network: "Le serveur Odoo ne peut pas joindre l’API. Faites vérifier HTTPS sortant, DNS et proxy. L’accès depuis le navigateur ne prouve pas l’accès du serveur.", keyError: "Clé API refusée. Créez une clé valide chez le fournisseur choisi, collez-la puis enregistrez. N’utilisez pas le mot de passe du site.", modelError: "Modèle introuvable ou non autorisé. Choisissez le modèle suggéré et vérifiez les droits API.", balance: "Crédit ou quota API épuisé. Consultez la facturation du fournisseur. L’abonnement au chat n’inclut pas de crédit API.", permission: "Accès API refusé. Vérifiez projet, permissions du modèle et région.", parameters: "Paramètres refusés par ce modèle. Choisissez le modèle suggéré.", configuration: "Choisissez un fournisseur et un modèle, saisissez sa clé API puis enregistrez. Changer de fournisseur nécessite sa propre clé.", guideSteps: "1. Activez le crédit API sur la plateforme officielle. 2. Choisissez le fournisseur et le modèle suggéré. 3. Collez la clé et enregistrez. 4. Autorisez le partage, testez la connexion puis la capacité d’analyse. L’abonnement au chat n’inclut pas de crédit API.", deepseekGuide: "DeepSeek : créez une clé API et vérifiez le solde.", openaiGuide: "OpenAI : clé de projet avec accès Responses API et crédit API.", claudeGuide: "Claude : clé Anthropic Console ; API Messages directe uniquement, hors Bedrock.", geminiGuide: "Gemini : clé Google AI Studio ; API Gemini directe uniquement, hors Vertex AI."},
};
for (const lang of Object.keys(CONFIG_COPY)) Object.assign(AI_COPY[lang], CONFIG_COPY[lang]);
const CONTEXT_COPY = {
    zh: {focus: "需要关注的影响", timingFacts: "来料与需求的时间间隔", too_long: "AI 报告超过服务运行限制，未接受该报告。", unreservedStock: "未预留现货", balanceEvidence: "查看情景余量来源", available: "供给量", allocated: "已分配", remainder: "未分配", balanceScope: "以下为已知情景事件后的余量，不是当前在库量。"},
    en: {focus: "Impacts needing attention", timingFacts: "Arrival and need timing", too_long: "AI report exceeded the service resource limit and was rejected.", unreservedStock: "Unreserved current stock", balanceEvidence: "View scenario remainder by source", available: "Supply", allocated: "Allocated", remainder: "Unallocated", balanceScope: "Balances after known scenario events, not current on-hand stock."},
    fr: {focus: "Impacts à examiner", timingFacts: "Dates d’arrivée et de besoin", too_long: "Le rapport IA dépasse la limite de ressources du service et a été refusé.", unreservedStock: "Stock actuel non réservé", balanceEvidence: "Voir le solde du scénario par source", available: "Approvisionnement", allocated: "Affecté", remainder: "Non affecté", balanceScope: "Soldes après les événements connus du scénario, pas le stock actuel."},
};

CONTEXT_COPY.zh.language = "AI 正文语言与界面语言不一致，未接受该报告。缺口计算结果保留。";
CONTEXT_COPY.en.language = "AI narrative does not match the interface language and was rejected. Calculation results remain available.";
CONTEXT_COPY.fr.language = "La langue du texte IA ne correspond pas à celle de l’interface. Rapport refusé ; les résultats du calcul sont conservés.";
CONTEXT_COPY.zh.scenarioAvailableAt = "情景可用时间";
CONTEXT_COPY.en.scenarioAvailableAt = "Scenario available at";
CONTEXT_COPY.fr.scenarioAvailableAt = "Disponibilité dans le scénario";

Object.assign(CONTEXT_COPY.zh, {
    originalAIReport: "AI 原文（文字和建议均需复核）", evidenceChecks: "按计算证据需要复核的事项",
    aiVerified: "默认影响与复核事项来自本次计算证据。模型原文未经过完整语义验证，展开后仍需业务复核。",
    checkLate: "核实 {source} 用于 {mo} 的 {quantity} {unit} 能否赶上用料时间 {need}；按当前假设，这些材料到 {arrival} 才可用。到货时间或分配改变后需重新计算。",
    checkMissing: "全部已知供给到位后，{mo} 仍缺 {quantity} {unit}。核实额外来源及可用时间，形成新情景后重新计算。",
    checkMissingWithLate: "即使把用于 {mo} 的晚到材料提前，赶上用料时间，仍要另补 {quantity} {unit}。如果这些材料仍晚到，用料时一共缺 {scenario} {unit}；需核实能及时供货的方案并重新计算。",
    calculatedRisk: "按本次计算核对的材料风险", originalAISummary: "AI 原始摘要（需复核）",
    lateSource: "晚到材料来源", lateSourceFact: "晚到来源：{source} · {quantity} {unit} · {arrival} 可用。",
    sourceAllocationHelp: "以下来源按本次测算分配；到货时间或分配改变后，需重新计算。",
    riskCovered: "本次范围内 {count} 条制造需求均能在需求时点获得材料，无新增缺口。",
    riskNew: "{mo} · 用料时间 {need}\n按原到货计划，用料时不缺料；按假设延期到货，用料时缺 {scenario} {unit}。",
    riskExisting: "{mo} · 用料时间 {need}\n按原到货计划，用料时缺 {baseline} {unit}；按假设延期到货，用料时缺 {scenario} {unit}。",
    riskDifference: "延期使这个时点多缺 {added} {unit}（{scenario} − {baseline} = {added}）。",
    riskFull: "按假设到货，材料可在 {full} 全部补齐。",
    riskUnfilled: "全部已知供给到位后，仍缺 {quantity} {unit}，无法确定全部补齐日期。",
});
Object.assign(CONTEXT_COPY.en, {
    originalAIReport: "Original AI text and suggestions (review required)", evidenceChecks: "Checks grounded in calculation evidence",
    aiVerified: "Default impacts and checks come from this calculation evidence. AI text has not had a full semantic validation and requires review when expanded.",
    checkLate: "Confirm whether the {quantity} {unit} allocated from {source} to {mo} can be available at the need time {need}; current scenario availability is {arrival}. Recalculate after any date or allocation change.",
    checkMissing: "After all known supply arrives, {mo} still lacks {quantity} {unit}. Confirm additional supply and availability dates, then calculate a new scenario.",
    checkMissingWithLate: "Even if all late material allocated to {mo} in this scenario becomes timely, {quantity} {unit} of additional supply is still needed. If that material stays late, the total gap at need is {scenario} {unit}; confirm a timely supply proposal and recalculate.",
    calculatedRisk: "Material risk checked against this calculation", originalAISummary: "Original AI summary (review required)",
    lateSource: "Late material source", lateSourceFact: "Late source: {source} · {quantity} {unit} · available {arrival}.",
    sourceAllocationHelp: "Sources follow this calculation's allocation. Recalculate after changes to arrivals or allocations.",
    riskCovered: "All {count} manufacturing demands in scope are covered at their need times, with no added shortage.",
    riskNew: "{mo} · Need time {need}\nWith the original arrival plan, nothing is short at this time; with the assumed delayed arrival, {scenario} {unit} are short at this same time.",
    riskExisting: "{mo} · Need time {need}\nWith the original arrival plan, {baseline} {unit} are short at this time; with the assumed delayed arrival, {scenario} {unit} are short at this same time.",
    riskDifference: "Delay adds {added} {unit} to the shortage at this time ({scenario} − {baseline} = {added}).",
    riskFull: "With the assumed arrival, all material is available at {full}.",
    riskUnfilled: "After all known supply arrives, {quantity} {unit} remain uncovered; full coverage time is unknown.",
});
Object.assign(CONTEXT_COPY.fr, {
    originalAIReport: "Texte et suggestions IA originaux (à vérifier)", evidenceChecks: "Vérifications fondées sur les données du calcul",
    aiVerified: "Les impacts et vérifications affichés proviennent des données du calcul. Le texte IA n’a pas été entièrement validé sur le plan sémantique et doit être vérifié après ouverture.",
    checkLate: "Confirmer si les {quantity} {unit} affectés de {source} à {mo} peuvent être disponibles au moment du besoin {need} ; disponibilité du scénario : {arrival}. Recalculer après toute modification de date ou d’affectation.",
    checkMissing: "Après tous les approvisionnements connus, il manque encore {quantity} {unit} pour {mo}. Confirmer un apport complémentaire et ses dates, puis calculer un nouveau scénario.",
    checkMissingWithLate: "Même si toute la matière tardive affectée à {mo} dans ce scénario devient disponible à temps, un apport complémentaire de {quantity} {unit} reste nécessaire. Si elle reste tardive, le manque total au besoin est de {scenario} {unit} ; confirmer une proposition disponible à temps et recalculer.",
    calculatedRisk: "Risque matière vérifié par le calcul", originalAISummary: "Résumé IA original (à vérifier)",
    lateSource: "Source de matière tardive", lateSourceFact: "Source tardive : {source} · {quantity} {unit} · disponible le {arrival}.",
    sourceAllocationHelp: "Les sources suivent les affectations de ce calcul. Recalculer après toute modification des arrivées ou affectations.",
    riskCovered: "Les {count} besoins de fabrication sont couverts à leurs dates de besoin, sans manque supplémentaire.",
    riskNew: "{mo} · Date du besoin {need}\nAvec le plan d’arrivée initial, rien ne manque à cette date ; avec l’arrivée retardée supposée, il manque {scenario} {unit} à cette même date.",
    riskExisting: "{mo} · Date du besoin {need}\nAvec le plan d’arrivée initial, il manque {baseline} {unit} à cette date ; avec l’arrivée retardée supposée, il manque {scenario} {unit} à cette même date.",
    riskDifference: "Le retard augmente le manque à cette date de {added} {unit} ({scenario} − {baseline} = {added}).",
    riskFull: "Avec l’arrivée supposée, toute la matière est disponible le {full}.",
    riskUnfilled: "Après tous les approvisionnements connus, il manque encore {quantity} {unit} ; la date de couverture complète est inconnue.",
});

const UX_COPY = {
    zh:{overview:"本次影响总览",overviewCount:"本次涉及 {total} 张制造单，其中 {affected} 张用料时缺料或补足时间未定。",overviewCovered:"本次涉及的 {total} 张制造单均能按时获得该材料。",overviewEmpty:"本次范围内没有制造需求。",earliestNeed:"最早需关注的用料时间",earliestTied:"同一时点涉及 {count} 张制造单",overviewFinal:"全部已知到货后仍缺",overviewDetails:"查看逐单影响与复核事项",plannedArrival:"明细原计划到货",scenarioArrival:"本次假设到货",dateComparison:"到货日期对照"},
    en:{overview:"Impact overview",overviewCount:"This scope includes {total} manufacturing orders; {affected} are short at need or have unknown coverage timing.",overviewCovered:"All {total} manufacturing orders in this scope receive this material on time.",overviewEmpty:"There is no manufacturing demand in this scope.",earliestNeed:"Earliest material need requiring attention",earliestTied:"{count} manufacturing orders share this need time",overviewFinal:"Still short after all known arrivals",overviewDetails:"View order impacts and review checks",plannedArrival:"Purchase line planned arrival",scenarioArrival:"Scenario arrival",dateComparison:"Arrival date comparison"},
    fr:{overview:"Vue d’ensemble des impacts",overviewCount:"Ce périmètre comprend {total} ordres de fabrication ; {affected} manquent de matière au besoin ou ont une couverture de date inconnue.",overviewCovered:"Les {total} ordres de ce périmètre disposent de cette matière à temps.",overviewEmpty:"Aucun besoin de fabrication dans ce périmètre.",earliestNeed:"Premier besoin de matière à examiner",earliestTied:"{count} ordres de fabrication partagent cette date de besoin",overviewFinal:"Manque après toutes les arrivées connues",overviewDetails:"Voir les impacts par ordre et les vérifications",plannedArrival:"Arrivée prévue sur la ligne d’achat",scenarioArrival:"Arrivée du scénario",dateComparison:"Comparaison des dates d’arrivée"},
};

Object.assign(UX_COPY.zh,{overviewGap:"用料时缺料",overviewCoverage:"按假设到货可补齐",overviewUnfilled:"已知到货后仍缺 {quantity} {unit}，补齐时间未定",overviewUnknown:"材料补足时间未定",inputsChanged:"到货假设已变更，请重新分析。上次结果保留在下方，仅供对照。",historyTitle:"上次假设，仅供对照",historyHelp:"以下是上次读取时的计算与方案，不代表当前假设或最新业务状态。本页保留最近一次结果，刷新页面后清除。",historyOptions:"当时的方案对比",historyNeed:"用料时间",historyGap:"用料时缺料",historyFull:"材料补齐时间",historyRead:"上次读取时间",historyArrival:"上次假设到货",historyMoves:"当时的拟调整"});
Object.assign(UX_COPY.en,{overviewGap:"Short at material need",overviewCoverage:"Coverage under the assumed arrival",overviewUnfilled:"Still short {quantity} {unit} after known arrivals; coverage time unknown",overviewUnknown:"Material coverage time is unknown",inputsChanged:"Arrival assumption changed. Analyze again. The previous result below is retained for comparison only.",historyTitle:"Previous assumption · comparison only",historyHelp:"These calculations and options reflect the previous read, not the current assumption or latest business state. This page retains the last result; reloading clears it.",historyOptions:"Options calculated at that time",historyNeed:"Need time",historyGap:"Short at need",historyFull:"Material coverage time",historyRead:"Previous read time",historyArrival:"Previous assumed arrival",historyMoves:"Transfers proposed at that time"});
Object.assign(UX_COPY.fr,{overviewGap:"Manque à la date du besoin",overviewCoverage:"Couverture selon l’arrivée supposée",overviewUnfilled:"Manque restant après les arrivées connues : {quantity} {unit} ; date de couverture inconnue",overviewUnknown:"Date de couverture matière inconnue",inputsChanged:"Hypothèse d’arrivée modifiée. Relancez l’analyse. Le résultat précédent reste ci-dessous, uniquement pour comparaison.",historyTitle:"Hypothèse précédente · comparaison uniquement",historyHelp:"Ces calculs et options reflètent la lecture précédente, pas l’hypothèse actuelle ni les dernières données métier. Cette page conserve le dernier résultat ; l’actualisation l’efface.",historyOptions:"Options calculées à ce moment",historyNeed:"Date du besoin",historyGap:"Manque au besoin",historyFull:"Date de couverture matière",historyRead:"Lecture précédente",historyArrival:"Arrivée supposée précédente",historyMoves:"Réaffectations proposées à ce moment"});

const VALIDATION_COPY = {
    zh: {row: "第 {row} 条需求：", risk: "风险等级与本次计算不一致。", count: "需求明细数量不一致，零缺口需求也必须保留。", demand: "需求或制造单引用不一致/重复。", date: "需求时间或材料补足时间与证据不一致。", number: "缺口数量与计算结果不一致。", missing_citation: "缺少该需求必须包含的证据引用。", unknown_citation: "引用了本次未读取的证据。", reads: "七类证据尚未全部读取。", sections: "未说明分析范围或限制。"},
    en: {row: "Demand {row}: ", risk: "Risk grade differs from this calculation.", count: "Demand count differs; include zero-shortage demands too.", demand: "Demand/MO reference differs or is duplicated.", date: "Need or material availability time differs from evidence.", number: "Shortage quantity differs from the calculation.", missing_citation: "Required demand citations are missing.", unknown_citation: "Cites evidence not read in this task.", reads: "Not all seven evidence tools were read.", sections: "Scope limits are missing."},
    fr: {row: "Besoin {row} : ", risk: "Le niveau de risque diffère du calcul.", count: "Nombre de besoins différent ; inclure aussi ceux sans manque.", demand: "Référence du besoin/de l’ordre différente ou dupliquée.", date: "Date du besoin ou de disponibilité différente des données.", number: "Quantité manquante différente du calcul.", missing_citation: "Références obligatoires du besoin manquantes.", unknown_citation: "Référence à des données non consultées.", reads: "Les sept outils n’ont pas tous été consultés.", sections: "Limites de l’analyse manquantes."},
};

Object.assign(UX_COPY.zh,{resumed:'已恢复复核情景，并自动读取当前计算与核实进度；本次返回不调用 AI。需要新解读时可点击 AI 分析或推荐。',resumeUnavailable:'原情景的采购明细已不在可分析范围内，请返回采购单核实。'});
Object.assign(UX_COPY.en,{resumed:'Review assumptions restored; calculations and task progress refresh without calling AI. Generate AI analysis or recommendations when needed.',resumeUnavailable:'The original purchase line is no longer available for analysis. Check the purchase order.'});
Object.assign(UX_COPY.fr,{resumed:'Scénario restauré : calculs et suivi actualisés sans appel IA. Générer une nouvelle analyse IA au besoin.',resumeUnavailable:'La ligne d’origine ne peut plus être analysée. Vérifier la commande.'});
export class MaterialDelayAction extends Component {
    static template = "material_delay_impact.Action";
    static components = { ReallocationPanel };
    static props = owlApi.useProps ? undefined : ["*"];

    setup() {
        if (owlApi.useProps) this.props = owlApi.useProps();
        this.orm = useService("orm");
        this.action = useService("action");
        // Odoo reconstructs a client action from route state on browser Back or
        // refresh. Its active_id replaces the initial button's custom params.
        const action = this.props.action;
        const rawId = action.params?.order_id ?? action.context?.active_id ?? action.params?.active_id;
        const numericId = typeof rawId === "number" || (typeof rawId === "string" && /^\d+$/.test(rawId))
            ? Number(rawId) : NaN;
        this.orderId = Number.isSafeInteger(numericId) && numericId > 0 ? numericId : null;
        this.scopeKey = JSON.stringify([user.userId, user.context.allowed_company_ids || []]);
        let saved = [this.props.state, this.props.globalState, action.params?.globalState]
            .find((item) => item?.orderId === this.orderId && item.scopeKey === this.scopeKey);
        const resume=action.params || {};
        let resumed=false;
        const resumeRequested=resume.mdic_line != null;
        if(resume.mdic_line != null){
            const line=String(resume.mdic_line), zone=resume.mdic_tz;
            const date=typeof resume.mdic_arrival==='string' && resume.mdic_arrival.length<=64 && /(?:Z|[+-]\d{2}:\d{2})$/.test(resume.mdic_arrival) ? DateTime.fromISO(resume.mdic_arrival,{setZone:true}) : null;
            if(/^\d{1,12}$/.test(line) && Number(line)>0 && typeof zone==='string' && zone.length<=64 && date?.isValid && DateTime.now().setZone(zone).isValid){
                saved={orderId:this.orderId,scopeKey:this.scopeKey,lineId:line,arrival:date.setZone(zone).toFormat("yyyy-MM-dd'T'HH:mm"),timezone:zone};
                resumed=true;
            }
        }
        const preferred = user.context.lang || "en_US";
        this.accountLanguage = preferred;
        this.reportToken = null;
        this.detached = false;
        this.observedAITask = null;
        this.state = useState({
            // The account language is authoritative, including on restoration
            // of an older action state containing a former language choice.
            lang: preferred.startsWith("zh") ? "zh" : preferred.startsWith("fr") ? "fr" : "en",
            timezone: saved?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
            shared: null, options: null, lineId: "", arrival: "", busy: false, error: "", report: null, restoredReport: false,
            previousToken: saved?.previousToken || null, inputsChanged: false, resumed, resumeReview: false,
            ai: null, aiBusy: false, aiError: "", aiConsent: false, showSettings: false, settingsBusy: false,
            config: null, provider: "deepseek", model: "deepseek-flash", key: "", configMessage: "", customModel: false, configUsage: null,
        });
        // Browser Back rebuilds from globalState; breadcrumbs can reuse local
        // state. Register both so each navigation path retains the scenario.
        useSetupAction({ getLocalState: () => this.navigationState(), getGlobalState: () => this.navigationState() });
        onWillUnmount(() => { this.detached = true; });
        onMounted(() => {
            this.detached = false;
            const previous = navigationReports.get(this.reportToken);
            if (previous?.aiTask) this.followAI(previous.aiTask, this.state.report, this.reportToken);
        });
        onWillStart(async () => {
            if (!this.orderId) {
                this.state.error = this.t("missingOrder");
                return;
            }
            try {
                if(resumeRequested && !resumed)throw new Error('Invalid review assumptions');
                const shared = await this.orm.call('purchase.order','mdic_collaboration',[[this.orderId], saved?.lineId ? Number(saved.lineId) : null, resume.mdic_arrival || null]);
                if(shared){
                    this.state.shared=shared; this.state.report=shared.report;
                    this.state.lineId=String(shared.shared_line_id); this.state.arrival=DateTime.fromISO(shared.report.assumed_at).setZone(this.state.timezone).toFormat("yyyy-MM-dd'T'HH:mm");
                    this.state.resumed=false; return;
                }
                this.state.options = await this.orm.call("purchase.order", "mdic_options", [[this.orderId]]);
                // Route reconstruction does not carry the original action name.
                // Set the controller title explicitly for browser Back and breadcrumbs.
                this.env.config?.setDisplayName?.(`${this.t("title")} · ${this.state.options.order}`);
                if (!saved?.timezone) this.state.timezone = this.state.options.timezone || this.state.timezone;
                const savedLine = this.state.options.lines.find((line) => String(line.id) === saved?.lineId);
                if(resumed && !savedLine){
                    this.state.resumed=false;
                    throw new Error(this.t('resumeUnavailable'));
                }
                this.state.lineId = String((savedLine || this.state.options.lines[0]).id);
                if (savedLine && saved.arrival) this.state.arrival = saved.arrival;
                else this.setInitialDate();
                await this.loadConfig();
                const previous = navigationReports.get(saved?.reportToken);
                if (savedLine && previous && previous.scopeKey === this.scopeKey
                    && previous.orderId === this.orderId && previous.accountLanguage === this.accountLanguage
                    && previous.lineId === this.state.lineId && previous.arrival === this.state.arrival
                    && previous.timezone === this.state.timezone) {
                    // Access is checked by mdic_options before a cached report
                    // is shown. Label it as a previous snapshot, not live data.
                    this.state.report = previous.report;
                    this.state.ai = previous.ai || null;
                    this.state.restoredReport = true;
                    this.reportToken = saved.reportToken;
                    if (previous.aiTask) this.followAI(previous.aiTask, this.state.report, saved.reportToken);
                }
                if(!this.state.report && this.previousSnapshot)this.state.inputsChanged=true;
                if(resumed) {
                    // Refresh authorized calculations and task progress without
                    // a paid provider call just to follow up an existing task.
                    this.state.resumeReview=true;
                    await this.run(false);
                    this.state.resumed=!!this.state.report;
                }
            } catch (error) {
                this.state.error = error.data?.message || (resumeRequested ? this.t("resumeUnavailable") : this.t("failed"));
            }
        });
    }

    sharedNotice() {return ({zh:'这是分派时保存的共同方案。核实反馈可通过“刷新进度”更新；业务数据变化后，请计划员重新分析并分派。',en:'This is the shared plan saved when assigned. Feedback is current; ask the planner to reanalyze and assign again after business data changes.',fr:'Plan partagé enregistré lors de l’attribution. Les retours sont actualisés ; demandez une nouvelle analyse après modification des données.'})[this.state.lang];}
    t(key) { return UX_COPY[this.state.lang]?.[key] || CONTEXT_COPY[this.state.lang][key] || COMPACT_COPY[this.state.lang][key] || AI_COPY[this.state.lang][key] || COPY[this.state.lang][key] || key; }
    get plannedArrival() {
        // Never mix today's line plan with a restored historical report.
        if(this.state.report)return this.state.report.planned_at || null;
        return this.state.options?.lines.find(line=>String(line.id)===this.state.lineId)?.planned_at || null;
    }
    get scenarioArrival() {
        if(this.state.report)return this.state.report.assumed_at || null;
        const value=DateTime.fromISO(this.state.arrival || "",{zone:this.state.timezone});
        return value.isValid ? value.toISO() : null;
    }
    get impactOverview() {
        const report=this.state.report, rows=report?.rows || [];
        const identity=row=>row.mo_id || row.mo || row.ref;
        const affected=rows.filter(row=>row.delayed_shortage>0 || !row.full_at || (Number.isFinite(row.unfilled) && row.unfilled>0));
        const valid=affected.filter(row=>DateTime.fromISO(row.need_at).isValid);
        const first=valid.length?Math.min(...valid.map(row=>DateTime.fromISO(row.need_at).toMillis())):null;
        const earliest=[...new Map(valid.filter(row=>DateTime.fromISO(row.need_at).toMillis()===first).map(row=>[identity(row),row])).values()];
        return {total:new Set(rows.map(identity)).size,affected:new Set(affected.map(identity)).size,
            earliest,earliestRows:valid.filter(row=>DateTime.fromISO(row.need_at).toMillis()===first),earliestAt:earliest[0]?.need_at || null,
            finalKnown:Number.isFinite(report?.unfilled),final:report?.unfilled};
    }
    get previousSnapshot() {
        if(!this.state.options)return null;
        const previous=navigationReports.get(this.state.previousToken);
        return previous && previous.scopeKey===this.scopeKey && previous.orderId===this.orderId &&
            previous.accountLanguage===this.accountLanguage && previous.lineId===this.state.lineId &&
            previous.timezone===this.state.timezone ? previous : null;
    }
    historyDate(value,snapshot) {
        return value ? DateTime.fromISO(value).setZone(snapshot.timezone).toFormat("yyyy-MM-dd HH:mm") : this.t("unknown");
    }
    knownNumber(value) {
        return value==null || typeof value==="boolean" || value==="" || !Number.isFinite(Number(value)) ? this.t("unknown") : this.number(value);
    }
    hasResidual(row) { return Number.isFinite(row.unfilled) && row.unfilled>0; }
    rememberRecommendation(report,value) {
        const entry=navigationReports.get(this.reportToken);
        if(this.detached || this.state.report!==report || !entry || entry.report!==report)return;
        entry.previousOptions=JSON.parse(JSON.stringify(value));
    }
    fill(key, values) {
        return this.t(key).replace(/\{(\w+)\}/g, (_match, name) => values[name] ?? "");
    }
    calculatedGrade() {
        const rank = {low: 0, medium: 1, high: 2};
        return (this.state.report?.rows || []).reduce((grade, row) => {
            const current = row.grade || (row.delayed_shortage > 0 ? (row.full_at ? "medium" : "high") : "low");
            return rank[current] > rank[grade] ? current : grade;
        }, "low");
    }
    riskFacts() {
        const report = this.state.report;
        if (!report?.rows.length) return [{key: "empty", text: this.t("focusEmpty")}];
        const affected = report.rows.filter(row => row.delayed_shortage > 0 || !row.full_at)
            .sort((a, b) => DateTime.fromISO(a.need_at).toMillis() - DateTime.fromISO(b.need_at).toMillis());
        if (!affected.length) return [{key: "covered", text: this.fill("riskCovered", {count: this.number(report.rows.length)})}];
        return affected.map(row => {
            const atNeed = this.fill(row.baseline_shortage === 0 && row.new_shortage > 0 ? "riskNew" : "riskExisting", {
                mo: row.mo, need: this.date(row.need_at), unit: report.unit,
                baseline: this.number(row.baseline_shortage), scenario: this.number(row.delayed_shortage), added: this.number(row.new_shortage),
            });
            const afterSupply = row.full_at ? this.fill("riskFull", {full: this.date(row.full_at)})
                : Number.isFinite(row.unfilled) && row.unfilled > 0
                    ? this.fill("riskUnfilled", {quantity: this.number(row.unfilled), unit: report.unit})
                    : this.fill("focusBlocked", {mo: row.mo, need: this.date(row.need_at), quantity: this.number(row.delayed_shortage), unit: report.unit});
            const difference = row.new_shortage > 0 ? "\n" + this.fill("riskDifference", {
                baseline: this.number(row.baseline_shortage), scenario: this.number(row.delayed_shortage),
                added: this.number(row.new_shortage), unit: report.unit,
            }) : "";
            const sources = this.lateSupplies(row).map(item => this.fill("lateSourceFact", {
                source: item.name, quantity: this.number(item.quantity), unit: report.unit, arrival: this.date(item.at),
            }));
            return {key: row.ref, text: [atNeed + difference, ...sources, afterSupply].join("\n")};
        });
    }
    lateSupplies(row) {
        const need = DateTime.fromISO(row.need_at).toMillis();
        return (row.allocations || []).filter(item => item.quantity > 0 && DateTime.fromISO(item.at).toMillis() > need)
            .map(item => {
                const evidence = this.state.report.evidence.find(entry => entry.ref === item.ref);
                return {...item, name: this.sourceName(item.ref), model: evidence?.model, id: evidence?.id};
            });
    }
    hasLateSupplies() {
        return (this.state.report?.rows || []).some(row => this.lateSupplies(row).length > 0);
    }
    attention() {
        const report = this.state.report;
        if (!report?.rows.length) return [];
        const millis = (value) => DateTime.fromISO(value).toMillis();
        const rows = [...report.rows].sort((a, b) => millis(a.need_at) - millis(b.need_at));
        return rows.filter(row => row.delayed_shortage > 0 || !row.full_at).map(row => ({key: row.ref,
            text: this.fill(row.full_at ? "focusDelayed" : "focusBlocked", {
                mo: row.mo, quantity: this.number(row.delayed_shortage), unit: report.unit,
                need: this.date(row.need_at), full: this.date(row.full_at),
            })}));
    }
    reviewFacts() {
        // These are evidence-linked questions, not AI claims or tested remedies.
        // Length follows actual late allocations and final insufficiency.
        const report = this.state.report;
        if (!report?.rows.length) return [];
        const millis = (value) => DateTime.fromISO(value).toMillis();
        return [...report.rows].sort((a, b) => millis(a.need_at) - millis(b.need_at)).flatMap(row => {
            if (!(row.delayed_shortage > 0)) return [];
            const late = row.allocations.filter(item => millis(item.at) > millis(row.need_at));
            const checks = late.map((item, index) => ({key: `${row.ref}-late-${index}`, text: this.fill("checkLate", {
                source: this.sourceName(item.ref), mo: row.mo, quantity: this.number(item.quantity), unit: report.unit,
                need: this.date(row.need_at), arrival: this.date(item.at),
            })}));
            if (Number.isFinite(row.unfilled) && row.unfilled > 0) checks.push({key: `${row.ref}-missing`,
                text: this.fill(late.length ? "checkMissingWithLate" : "checkMissing", {
                    mo: row.mo, quantity: this.number(row.unfilled), scenario: this.number(row.delayed_shortage), unit: report.unit,
                })});
            return checks;
        });
    }
    timingFacts() {
        const report = this.state.report;
        if (!report?.rows.length) return [];
        const millis = (value) => DateTime.fromISO(value).toMillis();
        const receipts = new Set(report.evidence.filter(item => item.kind === "receipt").map(item => item.ref));
        const windows = report.rows.flatMap(row => {
            const incoming = row.allocations.filter(item => receipts.has(item.ref));
            if (!incoming.length) return [];
            const at = Math.max(...incoming.map(item => millis(item.at)));
            const gap = millis(row.need_at) - at;
            if (!Number.isFinite(gap) || gap < 0) return [];
            return [{row, gap, last: incoming.filter(item => millis(item.at) === at)}];
        }).sort((a, b) => a.gap - b.gap);
        return windows.map(({row, gap, last}) => {
            const minutes = Math.floor(gap / 60000);
            const interval = minutes < 1 ? this.t("underMinute") : minutes < 60
                ? this.fill("minutes", {n: this.number(minutes)})
                : this.fill("hours", {n: this.number(Math.floor(gap / 360000) / 10)});
            return {key: row.ref, text: this.fill("focusWindow", {
                mo: row.mo, quantity: this.number(last.reduce((total, item) => total + item.quantity, 0)),
                unit: report.unit, source: [...new Set(last.map(item => this.sourceName(item.ref)))].join(" / "),
                arrival: this.date(last[0].at), need: this.date(row.need_at), interval,
            })};
        });
    }
    remaining(row) {
        // Older restored reports may not include the final uncovered quantity.
        // Missing evidence must not be displayed as zero.
        return Number.isFinite(row.unfilled) ? this.number(row.unfilled) : "—";
    }
    number(value) {
        return new Intl.NumberFormat({ zh: "zh-CN", en: "en-US", fr: "fr-FR" }[this.state.lang],
            // Keep small nonzero material quantities visible. NumberFormat's
            // full fraction range avoids hiding shortages below 0.000001.
            { maximumFractionDigits: 20 }).format(value);
    }
    coverageDate(value, need, shortage, history=null) {
        const full=Date.parse(value), due=Date.parse(need);
        if((shortage===0 || typeof shortage==='string' && shortage.trim()!=='' && Number(shortage)===0) && Number.isFinite(full) && Number.isFinite(due) && full<=due)
            return ({zh:'用料时已满足',en:'Covered by need time',fr:'Couvert au moment du besoin'})[this.state.lang] || 'Covered by need time';
        return history ? this.historyDate(value,history) : this.date(value);
    }
    date(value) {
        if (!value) return this.t("unknown");
        return DateTime.fromISO(value).setZone(this.state.timezone).toFormat("yyyy-MM-dd HH:mm");
    }
    navigationState() {
        return { orderId: this.orderId, scopeKey: this.scopeKey, timezone: this.state.timezone,
            lineId: this.state.lineId, arrival: this.state.arrival, reportToken: this.reportToken,
            previousToken:this.state.previousToken };
    }
    invalidate(preservePrevious=false) {
        if(preservePrevious && this.state.report && navigationReports.has(this.reportToken))this.state.previousToken=this.reportToken;
        this.state.report = null; this.state.error = ""; this.state.restoredReport = false; this.reportToken = null;
        this.state.ai = null; this.state.aiError = ""; this.state.aiBusy = false;
    }
    setInitialDate() {
        const line = this.state.options?.lines.find((item) => String(item.id) === this.state.lineId);
        if (line) this.state.arrival = DateTime.fromISO(line.planned_at).setZone(this.state.timezone)
            .plus({ days: 1 }).toFormat("yyyy-MM-dd'T'HH:mm");
    }
    onLine(event) { this.state.resumed=false; this.state.lineId = event.target.value; this.invalidate(); this.state.previousToken=null; this.state.inputsChanged=false; this.setInitialDate(); }
    onArrival(event) { this.state.resumed=false; this.state.arrival = event.target.value; this.invalidate(true); this.state.inputsChanged=!!this.previousSnapshot; }
    onTimezone(event) { this.state.resumed=false; this.state.timezone = event.target.value; this.invalidate(); this.state.previousToken=null; this.state.inputsChanged=false; }
    async run(withAI=true) {
        if (this.state.busy || this.state.aiBusy || this.state.settingsBusy) return;
        const date = DateTime.fromISO(this.state.arrival, { zone: this.state.timezone });
        if (!this.state.lineId || !date.isValid
            || date.toFormat("yyyy-MM-dd'T'HH:mm") !== this.state.arrival
            || date.getPossibleOffsets().length !== 1) {
            this.state.error = this.t("invalid"); return;
        }
        this.state.busy = true;
        this.state.resumeReview=withAI === false;
        this.invalidate(true);
        try {
            this.state.report = await this.orm.call("purchase.order", "mdic_analyze",
                [[this.orderId], Number(this.state.lineId), date.toUTC().toISO(), this.state.timezone]);
            this.reportToken = `mdic-${++nextReportToken}`;
            navigationReports.set(this.reportToken, { ...this.navigationState(),
                accountLanguage: this.accountLanguage, report: this.state.report, ai: null });
            this.state.inputsChanged=false;
            this.state.resumed=false;
            while (navigationReports.size > MAX_NAVIGATION_REPORTS) {
                navigationReports.delete(navigationReports.keys().next().value);
            }
            if (withAI !== false && this.state.config?.configured && this.state.aiConsent) await this.runAI();
        } catch (error) {
            this.state.error = error.data?.message || this.t("failed");
        } finally { this.state.busy = false; }
    }
    sourceName(ref) {
        const item = this.state.report.evidence.find((entry) => entry.ref === ref);
        if (item) return item.purchase ? `${item.purchase} / ${item.label}` : item.label;
        if (ref.startsWith("stock.quants:")) return this.t("currentStock");
        return ref;
    }
    async loadConfig() {
        const value = await this.orm.call("purchase.order", "mdic_ai_status", [[this.orderId]]);
        this.state.config = value;
        this.state.provider = value.provider || "deepseek";
        this.state.model = value.model || "deepseek-flash";
        this.state.customModel = this.state.model !== value.presets?.[this.state.provider];
    }
    get configDirty() { return Boolean(this.state.key) || this.state.provider !== this.state.config?.provider || this.state.model !== this.state.config?.model; }
    configStatus() {
        if (this.configDirty && this.state.config?.configured) return this.t('pendingSave');
        const config = this.state.config;
        return this.t(!config?.configured ? 'notConfigured' : config.validation?.capable ? 'capabilityPassed' : config.validation?.connected ? 'connectionPassed' : 'savedUntested');
    }
    configUsageText() {
        const value = this.state.configUsage;
        return Number.isInteger(value?.total_tokens) ? `${value.total_tokens} tokens` : this.t('unknownUsage');
    }
    chooseModel(event) {
        this.state.customModel = event.target.value === 'custom';
        if (!this.state.customModel) this.state.model = this.state.config?.presets?.[this.state.provider] || '';
    }
    toggleSettings() { this.state.showSettings = !this.state.showSettings; this.state.key = ""; this.state.configMessage = ""; }
    onProvider(event) { this.state.provider = event.target.value; this.state.model = this.state.config?.presets?.[this.state.provider] || ''; this.state.key = ""; this.state.customModel = false; this.state.configMessage = ''; this.state.configUsage = null; }
    onModel(event) { this.state.model = event.target.value; }
    onKey(event) { this.state.key = event.target.value; }
    aiMessage(code, detail) {
        const message = this.t(code === "key" ? "keyError" : code === "model" ? "modelError" : code === 'capability' ? 'capabilityError' : code);
        const copy = VALIDATION_COPY[this.state.lang];
        const specific = code === "validation" && copy[detail?.reason];
        if (!specific) return message;
        const row = Number.isInteger(detail.row) && detail.row >= 1 && detail.row <= 20 ? copy.row.replace("{row}", detail.row) : "";
        return `${message} ${row}${specific}`;
    }
    async settingsOperation(operation) {
        if (this.state.settingsBusy || this.state.busy || this.state.aiBusy) return;
        this.state.settingsBusy = true; this.state.configMessage = ""; this.state.configUsage = null;
        try {
            const args = operation === "save" ? [[this.orderId], this.state.provider, this.state.model, this.state.key]
                : ['test', 'capability'].includes(operation) ? [[this.orderId], Date.now().toString(36) + "_" + Math.random().toString(36).slice(2) + "_" + Math.random().toString(36).slice(2)]
                : [[this.orderId]];
            const value = await this.orm.call("purchase.order", `mdic_ai_${operation}`, args);
            this.state.configMessage = value.status === "failed" ? this.aiMessage(value.code) : value.validation_saved === false ? this.t('validationNotSaved') : this.t({save: "saved", remove: "removed", test: "connected", capability: "capable"}[operation]);
            if (value.usage_details) this.state.configUsage = value.usage || {};
            if (value.status !== "failed" && ['save', 'remove'].includes(operation)) {
                this.state.ai = null; this.state.aiError = "";
                const saved = navigationReports.get(this.reportToken);
                if (saved) { saved.ai = null; saved.aiTask = null; }
            }
            await this.loadConfig();
        } catch (error) { this.state.configMessage = this.t("network"); }
        finally { this.state.key = ""; this.state.settingsBusy = false; }
    }
    saveConfig() { return this.settingsOperation("save"); }
    removeConfig() { return this.settingsOperation("remove"); }
    onAIConsent(event) { this.state.aiConsent = event.target.checked; }
    testConfig() {
        if (this.configDirty) { this.state.configMessage = this.t('pendingSave'); return; }
        if (!this.state.aiConsent) { this.state.configMessage = this.t("aiConsent"); return; }
        return this.settingsOperation("test");
    }
    testCapability() {
        if (this.configDirty) { this.state.configMessage = this.t('pendingSave'); return; }
        if (!this.state.aiConsent) { this.state.configMessage = this.t('aiConsent'); return; }
        return this.settingsOperation('capability');
    }
    async runAI() {
        if (!this.state.aiConsent) { this.state.aiError = this.t("aiConsent"); return; }
        if (this.state.aiBusy || !this.state.report) return;
        const report = this.state.report;
        const token = this.reportToken;
        const saved = navigationReports.get(token);
        if (!saved) { this.state.aiError = this.t("expired"); return; }
        if (saved?.aiTask?.status === "pending") return this.followAI(saved.aiTask, report, token);
        const task = {status: "pending", value: null, code: null, detail: null};
        if (saved) { saved.ai = null; saved.aiTask = task; }
        const orm = this.env.services.orm;
        const args = [[this.orderId], report.ai_token, Number(this.state.lineId)];
        // This bounded, tab-memory task outlives the client action. useService's
        // lifecycle wrapper can suppress its promise after the action is destroyed,
        // so the request uses the underlying service. No credentials are cached.
        task.promise = Promise.resolve().then(() => orm.call("purchase.order", "mdic_ai_analyze", args)).then(value => {
            if (value.status === "verified" && value.snapshot_id === report.snapshot_id) {
                task.value = value; task.status = "completed";
            } else {
                task.code = value.code || "validation"; task.detail = value.detail; task.status = "failed";
            }
        }).catch(() => { task.code = "network"; task.status = "failed"; }).then(() => {
            const current = navigationReports.get(token);
            if (current?.aiTask === task) current.ai = task.value;
        });
        return this.followAI(task, report, token);
    }
    async followAI(task, report, token) {
        if (this.observedAITask === task && task.status === "pending") return;
        const render = () => {
            if (this.detached || this.state.report !== report || this.reportToken !== token
                || navigationReports.get(token)?.aiTask !== task) return;
            this.state.aiBusy = task.status === "pending";
            this.state.ai = task.value;
            this.state.aiError = task.status === "failed" ? this.aiMessage(task.code, task.detail) : "";
        };
        render();
        if (task.status === "pending") {
            this.observedAITask = task;
            await task.promise;
            if (this.observedAITask === task) this.observedAITask = null;
            render();
        }
    }
    openRecord(model, id) {
        return this.action.doAction({ type: "ir.actions.act_window", res_model: model,
            res_id: id, views: [[false, "form"]], target: "current" });
    }
    back() {
        if (this.orderId) return this.openRecord("purchase.order", this.orderId);
        return this.action.doAction({ type: "ir.actions.act_window", res_model: "purchase.order",
            views: [[false, "list"], [false, "form"]], target: "current" });
    }
}

registry.category("actions").add("material_delay_impact", MaterialDelayAction);
