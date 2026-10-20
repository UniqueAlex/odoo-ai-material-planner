/** @odoo-module **/
import * as owlApi from "@odoo/owl";
import { user } from "@web/core/user";

const { Component, onMounted, onWillUnmount } = owlApi;
const useState = owlApi.useState || owlApi.proxy;
const memory = new Map();
const clone = value => JSON.parse(JSON.stringify(value));
// A user action gets one identity; transport retries keep the same RPC args.
const requestId = () => Date.now().toString(36) + "_" + Math.random().toString(36).slice(2) + "_" + Math.random().toString(36).slice(2);
const DECISION_TEXT = {
 zh:{adoption:'采用前提',coordination:'具体协调目标',conditional:'满足以下条件后再考虑调料',priority_conflict:'此方案影响已标记高优先级订单，需先确认优先级取舍',keepDecision:'保持当前分配；仍需落实以下供料目标',decisionUnavailable:'采用条件尚未读取，请重新比较方案。',decisionScope:'以下是本方案的协调目标，不是已确认到货或生产承诺。缺料总目标与分项是同一批需求，不重复相加。',accept_harm:'计划员：确认能接受该订单缺料或材料等待的增加。',release_reservation:'仓储：确认这批预留仍未领用，并允许释放；当前试算没有解除预留。',partial_production:'生产：核实已有材料能否支持部分投产；若可以，先评估挪走材料造成的损失。',other_none:'当前没有其他未完成的正数量原料需求；仍需核实生产安排。',other_reserved:'其他未完成原料当前均已预留；仍需核实现场可用性。',other_unconfirmed:'其他原料尚未全部确认预留。先确认能否同时备齐，不能据此认定可生产。',other_unknown:'其他原料备齐情况未知，需生产核实。',capacity:'生产：确认人员、设备和工序安排；本次未计算产能。',warehouse_planner:'仓储 / 计划员',purchasing_warehouse:'采购 / 仓储',purchasing_planner:'采购 / 计划员',planner:'计划员',coordinate_transfer:'确认调料',expedite:'协调提前可用',confirm_receipt:'落实已计入的来料',additional_supply:'寻找额外供应',gap_target:'用料时需解决的总缺料',by:'最晚需要可用',scenarioAvailable:'本情景可用时间',lateSupply:'该来源目前晚于用料时间，单独调料仍不能按时补上',gapSplit:'其中需提前的已知来料 {late} {unit}；全部已知到货后仍无来源 {remaining} {unit}。',unknownSupplier:'来源尚未落实',confirmOnly:'能否提前或增加供应需确认，并重新试算。'},
 en:{adoption:'Conditions for adoption',coordination:'Coordination targets',conditional:'Consider transfers only after these checks',priority_conflict:'This option harms a recorded high-priority order; agree the priority tradeoff first',keepDecision:'Keep allocation; follow up these supply targets',decisionUnavailable:'Adoption evidence has not been read. Compare options again.',decisionScope:'These are targets, not confirmed arrivals or production promises. Total gaps and their parts describe the same demand; do not add them together.',accept_harm:'Planner: accept the increased shortage or material waiting for this order.',release_reservation:'Warehouse: confirm stock is still unpicked and its reservation may be released. The simulation releases nothing.',partial_production:'Production: check whether existing material enables partial production; assess that loss before moving it.',other_none:'No other unfinished positive-quantity component demand is recorded; verify production arrangements.',other_reserved:'Other unfinished components are currently reserved; verify physical availability.',other_unconfirmed:'Other components are not all confirmed reserved. Confirm they can be ready together before assuming production is possible.',other_unknown:'Other-component readiness is unknown; production must check.',capacity:'Production: verify people, equipment and operations. Capacity is not calculated here.',warehouse_planner:'Warehouse / planner',purchasing_warehouse:'Purchasing / warehouse',purchasing_planner:'Purchasing / planner',planner:'Planner',coordinate_transfer:'Confirm transfer',expedite:'Seek earlier availability',confirm_receipt:'Confirm allocated inbound supply',additional_supply:'Find additional supply',gap_target:'Total shortage to resolve at need',by:'Required available by',scenarioAvailable:'Scenario availability',lateSupply:'This source is late; reallocation alone cannot cover the need on time',gapSplit:'Known arrivals to bring forward: {late} {unit}; no known source even after all arrivals: {remaining} {unit}.',unknownSupplier:'Source not established',confirmOnly:'Confirm feasibility and recalculate any earlier or additional supply.'},
 fr:{adoption:'Conditions d’adoption',coordination:'Objectifs de coordination',conditional:'Envisager le transfert après ces vérifications',priority_conflict:'Cette option pénalise un ordre prioritaire : confirmer le compromis',keepDecision:'Conserver l’affectation et suivre ces objectifs',decisionUnavailable:'Conditions non lues. Comparez à nouveau les options.',decisionScope:'Objectifs, non promesses de réception ou de production. Le manque total et ses parties ne doivent pas être additionnés.',accept_harm:'Planification : accepter le manque ou l’attente supplémentaire de cet ordre.',release_reservation:'Entrepôt : confirmer que le stock n’est pas prélevé et que sa réservation peut être libérée. La simulation ne la libère pas.',partial_production:'Production : vérifier si la matière permet une fabrication partielle et évaluer sa perte avant transfert.',other_none:'Aucun autre besoin de composant inachevé de quantité positive enregistré ; vérifier l’organisation.',other_reserved:'Les autres composants inachevés sont réservés ; vérifier leur disponibilité physique.',other_unconfirmed:'Les autres composants ne sont pas tous réservés. Vérifier leur disponibilité simultanée avant de conclure que la fabrication est possible.',other_unknown:'Disponibilité des autres composants inconnue ; à vérifier par la production.',capacity:'Production : vérifier personnel, équipements et opérations. La capacité n’est pas calculée.',warehouse_planner:'Entrepôt / planification',purchasing_warehouse:'Achats / entrepôt',purchasing_planner:'Achats / planification',planner:'Planification',coordinate_transfer:'Confirmer le transfert',expedite:'Demander une disponibilité anticipée',confirm_receipt:'Confirmer l’approvisionnement affecté',additional_supply:'Trouver une fourniture supplémentaire',gap_target:'Manque total à résoudre au besoin',by:'Disponibilité requise au plus tard',scenarioAvailable:'Disponibilité simulée',lateSupply:'Source tardive : le transfert seul ne couvre pas le besoin à temps',gapSplit:'Arrivées connues à avancer : {late} {unit} ; sans source même après toutes les arrivées : {remaining} {unit}.',unknownSupplier:'Source non établie',confirmOnly:'Confirmer la faisabilité et recalculer toute fourniture anticipée ou supplémentaire.'}
};
const TEXT = {
    zh: { title: "调料方案试算", intro: "比较同物料调料的收益与代价。试算不改变实际预留或制造单。", open: "准备调料试算", refresh: "重新读取", loading: "正在读取并计算…", receiver: "希望改善的制造单", candidate: "材料来源与让料订单", choose: "请选择", noCandidates: "没有找到较晚制造单可让出的分配。当前结果不代表有可及时调入的材料。", qty: "试算数量", add: "加入方案", remove: "移除", compare: "比较方案", plan: "本次拟调整", source: "来源", donor: "让料订单", arrival: "材料可用时间", late: "晚于目标用料时间", timely: "不晚于目标用料时间", noEarlier: "不能提前当前补足时间", empty: "先选择来源与数量，加入方案后再比较。", before: "保持延期后分配", after: "调料后", shortage: "用料时缺料", full: "材料补足时间", final: "全部已知到货后仍缺", mo: "制造单", need: "用料时间", change: "变化", improved: "改善", worsened: "恶化", tradeoff: "有利有弊", unchanged: "未变", wait: "各订单材料等待时长之和", hours: "小时", unknown: "无法确定", caveat: "材料等待按用料时间到补足时间计算，不代表生产延期；日期未知的订单不会按零等待计入总数。", duplicate: "该来源与订单组合已加入；如需修改数量，请移除后重新加入。", invalid: "请选择来源并填写大于零的数量。", failed: "试算未完成。原分析结果仍保留，请重新读取并检查方案。", read: "本区读取时间", current: "当前库存（原预留给 {mo}）", ai: "AI 解读当前方案（可能收费）", aiReview: "AI 解读（需业务复核）", aiHelp: "以下文字针对本次调料方案；表格中的计算结果作为核对依据。", aiFailed: "AI 解读未完成；方案比较仍可使用。", aiRunning: "AI 正在解读当前方案…", checks: "待核实事项", configured: "配置 AI 后可解读此方案。", affects: "受影响订单", rowsHelp: "比较同一用料时点的缺料，并保留全部相关订单，包括未变化的订单。", stale: "库存、预留、日期或权限范围已变化，请重新读取后建立方案。", noDemand: "当前没有需要改善的缺料需求。", received: "实际已预留", virtual: "试算现货分配" },
    en: { title: "Material reallocation scenarios", intro: "Compare the benefits and costs of reallocating the same material. Actual reservations and manufacturing orders stay unchanged.", open: "Prepare reallocation", refresh: "Read current data", loading: "Reading and calculating…", receiver: "Demand to improve", candidate: "Source and donor order", choose: "Select", noCandidates: "No allocations from later demands were found. This does not establish that timely transferable material exists.", qty: "Scenario quantity", add: "Add to plan", remove: "Remove", compare: "Compare plan", plan: "Proposed transfers", source: "Source", donor: "Donor order", arrival: "Material available at", late: "After the target need", timely: "By the target need", noEarlier: "Does not advance current coverage", empty: "Choose a source and quantity, add it to the plan, then compare.", before: "Keep delayed allocation", after: "After reallocation", shortage: "Short at need", full: "Material fully available", final: "Still short after all known arrivals", mo: "Manufacturing order", need: "Need time", change: "Change", improved: "Improved", worsened: "Worsened", tradeoff: "Tradeoff", unchanged: "Unchanged", wait: "Sum of material waiting time across orders", hours: "hours", unknown: "Unknown", caveat: "Material waiting runs from need to material coverage, not production lateness. Unknown coverage dates are not counted as zero waiting.", duplicate: "This source and order combination is already in the plan. Remove it before changing its quantity.", invalid: "Select a source and enter a positive quantity.", failed: "The plan could not be calculated. The original analysis is retained. Read current data and check the plan.", read: "Data read for this section", current: "Current stock (originally reserved for {mo})", ai: "Explain this plan with AI (may incur charges)", aiReview: "AI interpretation (review required)", aiHelp: "This text describes the current reallocation plan. Check it against the calculated table.", aiFailed: "AI interpretation did not complete. The comparison remains available.", aiRunning: "AI is interpreting this plan…", checks: "Checks to make", configured: "Configure AI to interpret this plan.", affects: "Affected orders", rowsHelp: "Compare shortages at the same need time. All relevant orders are retained, including unchanged ones.", stale: "Stock, reservations, dates or access scope changed. Read current data and rebuild the plan.", noDemand: "No shortage demand currently needs improvement.", received: "Actual reservation", virtual: "Scenario stock allocation" },
    fr: { title: "Simulation de réaffectation de matière", intro: "Comparez les avantages et les coûts d’une réaffectation de la même matière. Les réservations et les ordres réels restent inchangés.", open: "Préparer une simulation", refresh: "Relire les données", loading: "Lecture et calcul…", receiver: "Besoin à améliorer", candidate: "Source et ordre cédant", choose: "Sélectionner", noCandidates: "Aucune affectation issue d’un besoin ultérieur n’a été trouvée. Cela ne prouve pas qu’une matière transférable soit disponible à temps.", qty: "Quantité simulée", add: "Ajouter au scénario", remove: "Retirer", compare: "Comparer le scénario", plan: "Réaffectations proposées", source: "Source", donor: "Ordre cédant", arrival: "Matière disponible le", late: "Après le besoin cible", timely: "Au plus tard au besoin cible", noEarlier: "N’avance pas la couverture actuelle", empty: "Choisissez une source et une quantité, ajoutez-les au scénario, puis comparez.", before: "Affectation avec retard conservée", after: "Après réaffectation", shortage: "Manque au besoin", full: "Matière entièrement disponible", final: "Manque après les arrivées connues", mo: "Ordre de fabrication", need: "Date du besoin", change: "Évolution", improved: "Amélioration", worsened: "Aggravation", tradeoff: "Compromis", unchanged: "Inchangé", wait: "Somme des attentes de matière des ordres", hours: "heures", unknown: "Inconnue", caveat: "L’attente de matière va du besoin à sa couverture et ne prédit pas le retard de production. Une date inconnue ne compte pas comme une attente nulle.", duplicate: "Cette combinaison figure déjà dans le scénario. Retirez-la pour modifier sa quantité.", invalid: "Sélectionnez une source et saisissez une quantité positive.", failed: "Le calcul n’a pas abouti. L’analyse initiale est conservée. Relisez les données et vérifiez le scénario.", read: "Données de cette section lues le", current: "Stock actuel (réservé initialement pour {mo})", ai: "Interpréter ce scénario avec l’IA (frais possibles)", aiReview: "Interprétation IA (à vérifier)", aiHelp: "Ce texte concerne le scénario actuel. Vérifiez-le avec le tableau calculé.", aiFailed: "L’interprétation IA n’a pas abouti. La comparaison reste disponible.", aiRunning: "L’IA interprète le scénario…", checks: "Vérifications à effectuer", configured: "Configurez l’IA pour interpréter ce scénario.", affects: "Ordres affectés", rowsHelp: "Comparez les manques à la même date de besoin. Tous les ordres concernés restent visibles, même inchangés.", stale: "Stock, réservations, dates ou droits modifiés. Relisez les données et recréez le scénario.", noDemand: "Aucun besoin en manque à améliorer actuellement.", received: "Réservation réelle", virtual: "Stock affecté en simulation" },
};
TEXT.zh.noChange="各订单保持当前延期情景下的缺料与补足时间。";
TEXT.en.noChange="Order shortages and coverage dates stay as in the current delay scenario.";
TEXT.fr.noChange="Les manques et dates de couverture restent ceux du scénario de retard actuel.";
TEXT.zh.aiBlocked="调料 AI 解读尚未通过文字核验，暂不开放；当前以方案比较表为准。";
TEXT.en.aiBlocked="AI reallocation interpretation has not passed narrative checks and is not available yet. Use the calculated comparison.";
TEXT.fr.aiBlocked="L’interprétation IA n’a pas encore passé les vérifications du texte et reste indisponible. Consultez la comparaison calculée.";
Object.assign(TEXT.zh,{autoTitle:"AI 方案建议",autoIntro:"自动比较现有材料的分配方式，按实际取舍展示方案。",auto:"AI 推荐方案",autoNoAI:"自动比较方案",manual:"手动试算（可选）",overall_wait:"整体材料等待优先",fewer_late_orders:"少影响订单优先",explicit_priority:"优先保护已标记的高优先级订单",earliest_need:"优先保护最早用料的订单",keep:"保持现有分配",steps:"具体调整",benefits:"受益与代价",evidence:"逐单比较",lateCount:"用料时缺料的订单",autoScope:"推荐来自本次已计算候选的比较；不是全局最优或实际生产排程。",noPriority:"当前没有区分订单优先级；最早用料与紧急订单是不同标准。",aiNotReady:"AI 本次未完成推荐解读，以下计算方案仍可比较。",aiPendingReview:"AI 推荐理由，需业务复核",autoFailed:"自动推荐未完成，原报告与手动方案仍保留。",moreSupply:"核实补充供应",confirm_arrival:"核实到货时间",confirm_reservation:"核实库存预留可否调整",review_priority:"核实订单优先级取舍",find_additional_supply:"核实剩余缺料的补充供应"});
Object.assign(TEXT.en,{autoTitle:"AI solution options",autoIntro:"Automatically compare available material allocations and show distinct tradeoffs.",auto:"AI recommendations",autoNoAI:"Compare options automatically",manual:"Manual scenario (optional)",overall_wait:"Prioritize overall material waiting",fewer_late_orders:"Prioritize fewer orders short at need",explicit_priority:"Protect recorded high-priority orders",earliest_need:"Protect the earliest material need",keep:"Keep the current allocation",steps:"Proposed changes",benefits:"Benefits and costs",evidence:"Order comparison",lateCount:"Orders short at need",autoScope:"Recommendations compare the candidates evaluated here; no global optimum or production schedule is established.",noPriority:"No distinct order priority is recorded. Earliest need is a different objective from urgency.",aiNotReady:"AI interpretation did not complete. The calculated alternatives remain available.",aiPendingReview:"AI recommendation rationale; business review required",autoFailed:"Recommendations did not complete. The original report and manual plan are retained.",confirm_arrival:"Confirm arrival timing",confirm_reservation:"Confirm whether reservations may change",review_priority:"Review order-priority tradeoffs",find_additional_supply:"Confirm supply for the remaining shortfall"});
Object.assign(TEXT.fr,{autoTitle:"Options de solution IA",autoIntro:"Comparez automatiquement les affectations possibles et leurs compromis.",auto:"Recommandations IA",autoNoAI:"Comparer automatiquement",manual:"Simulation manuelle (facultative)",overall_wait:"Privilégier l’attente totale",fewer_late_orders:"Privilégier moins d’ordres en manque",explicit_priority:"Protéger les ordres de priorité élevée enregistrée",earliest_need:"Protéger le besoin de matière le plus proche",keep:"Conserver l’affectation actuelle",steps:"Modifications proposées",benefits:"Avantages et coûts",evidence:"Comparaison par ordre",lateCount:"Ordres en manque au besoin",autoScope:"Les recommandations comparent les candidats calculés ici, sans garantir un optimum global ni un planning de production.",noPriority:"Aucune priorité distincte n’est enregistrée. Le besoin le plus proche ne définit pas l’urgence.",aiNotReady:"L’interprétation IA n’a pas abouti. Les options calculées restent disponibles.",aiPendingReview:"Motif IA à vérifier par le métier",autoFailed:"La recommandation n’a pas abouti. Le rapport et le scénario manuel sont conservés.",confirm_arrival:"Confirmer la date d’arrivée",confirm_reservation:"Vérifier si les réservations peuvent changer",review_priority:"Vérifier le compromis de priorité",find_additional_supply:"Confirmer un approvisionnement complémentaire"});

Object.assign(TEXT.zh,{decreased:"减少",increased:"增加",stable:"不变"});
Object.assign(TEXT.en,{decreased:"Decreased",increased:"Increased",stable:"Unchanged"});
Object.assign(TEXT.fr,{decreased:"Baisse",increased:"Hausse",stable:"Inchangé"});

Object.assign(TEXT.zh,{
    computedSummary:"按本次计算比较", aiExtra:"AI 补充解读（需业务复核）",
    aiFacts:"AI 选取的决策依据",aiFactsHelp:"AI 从本次计算中选取关注点；材料来源、数量和时间均来自本方案的计算证据。",
    aiExtraHelp:"以下是 AI 的补充意见；方案取舍以本卡片的计算摘要和逐单比较为依据。",
    waitSame:"各订单材料等待时长之和保持为 {after}。",
    waitLess:"各订单材料等待时长之和由 {before} 减少至 {after}，减少 {delta}。",
    waitMore:"各订单材料等待时长之和由 {before} 增加至 {after}，增加 {delta}。",
    waitUnknown:"各订单材料等待时长之和：{before} → {after}；存在无法确定的补足时间，不能判断整体等待是否减少。",
    lateSame:"用料时缺料的订单仍为 {after} 张。",
    lateLess:"用料时缺料的订单由 {before} 张减少至 {after} 张。",
    lateMore:"用料时缺料的订单由 {before} 张增加至 {after} 张。",
    residualZero:"全部已知到货后，本次材料需求均可覆盖。",
    residualPositive:"全部已知到货后，仍有 {quantity} {unit} 材料需求未覆盖。",
    residualUnknown:"全部已知到货后的剩余缺料无法确定。",
});
Object.assign(TEXT.en,{
    computedSummary:"Calculated comparison", aiExtra:"Additional AI interpretation (review required)",
    aiFacts:"Decision evidence selected by AI",aiFactsHelp:"AI selects the focus from this calculation. Sources, quantities and dates come from this option’s calculation evidence.",
    aiExtraHelp:"These are additional AI comments. Use the calculated summary and order comparison to assess this option.",
    waitSame:"Total material waiting across orders stays at {after}.",
    waitLess:"Total material waiting across orders decreases from {before} to {after}, a reduction of {delta}.",
    waitMore:"Total material waiting across orders increases from {before} to {after}, an increase of {delta}.",
    waitUnknown:"Total material waiting across orders: {before} → {after}. Unknown coverage dates prevent a conclusion about an overall reduction.",
    lateSame:"{after} orders remain short at their material need time.",
    lateLess:"Orders short at their material need time decrease from {before} to {after}.",
    lateMore:"Orders short at their material need time increase from {before} to {after}.",
    residualZero:"All material demand is covered after all known arrivals.",
    residualPositive:"After all known arrivals, {quantity} {unit} of material demand remains uncovered.",
    residualUnknown:"The remaining shortage after all known arrivals is unknown.",
});
Object.assign(TEXT.fr,{
    computedSummary:"Comparaison calculée", aiExtra:"Complément IA (à vérifier)",
    aiFacts:"Éléments de décision sélectionnés par l’IA",aiFactsHelp:"L’IA sélectionne les points à examiner dans ce calcul. Sources, quantités et dates proviennent des données calculées de cette option.",
    aiExtraHelp:"Ces commentaires complètent l’analyse. Évaluez le compromis à partir du résumé calculé et de la comparaison par ordre.",
    waitSame:"La somme des attentes de matière reste à {after}.",
    waitLess:"La somme des attentes de matière passe de {before} à {after}, soit une baisse de {delta}.",
    waitMore:"La somme des attentes de matière passe de {before} à {after}, soit une hausse de {delta}.",
    waitUnknown:"Somme des attentes de matière : {before} → {after}. Les dates de couverture inconnues empêchent de conclure à une baisse totale.",
    lateSame:"{after} ordres restent en manque à la date du besoin de matière.",
    lateLess:"Le nombre d’ordres en manque au besoin passe de {before} à {after}, en baisse.",
    lateMore:"Le nombre d’ordres en manque au besoin passe de {before} à {after}, en hausse.",
    residualZero:"Tous les besoins de matière sont couverts après toutes les arrivées connues.",
    residualPositive:"Après toutes les arrivées connues, {quantity} {unit} de besoin de matière restent non couverts.",
    residualUnknown:"Le manque restant après toutes les arrivées connues est inconnu.",
});

Object.assign(TEXT.zh,{noAdjustment:"本次用料需求均能按时满足，无需调料。",inspectOptions:"查看计算方案",noAdjustmentTitle:"保持现有分配，无需调整",copyOption:"复制复核摘要",copied:"复核摘要已复制。",copyFallback:"复核摘要已生成，请复制下方文字。",handoff:"方案复核摘要",handoffLabel:"可复制的方案复核摘要",handoffScope:"本方案仅供复核，未修改采购、库存预留或制造单。业务数据或分配变化后需重新分析。",planned:"明细原计划到货",assumed:"本次假设到货",material:"物料",option:"方案",unreservedStock:"当前未预留库存",confirmSupply:"与采购、仓储核实材料可用时间",confirmStock:"与仓储、计划员核实预留调整",noChecks:"按实际到货及业务安排复核后再执行。"});
Object.assign(TEXT.en,{noAdjustment:"All material needs in this scenario are covered on time. No reallocation is needed.",inspectOptions:"View calculated options",noAdjustmentTitle:"Keep the current allocation; no change needed",copyOption:"Copy review summary",copied:"Review summary copied.",copyFallback:"Review summary prepared. Copy the text below.",handoff:"Allocation review summary",handoffLabel:"Copyable allocation review summary",handoffScope:"For review only. Purchases, reservations and manufacturing orders have not changed. Analyze again after business data or allocations change.",planned:"Purchase line planned arrival",assumed:"Scenario arrival",material:"Material",option:"Option",unreservedStock:"Current unreserved stock",confirmSupply:"Confirm material availability with purchasing and warehouse",confirmStock:"Confirm reservation changes with warehouse and planner",noChecks:"Review actual arrivals and business plans before execution."});
Object.assign(TEXT.fr,{noAdjustment:"Tous les besoins de matière de ce scénario sont couverts à temps. Aucune réaffectation nécessaire.",inspectOptions:"Voir les options calculées",noAdjustmentTitle:"Conserver l’affectation actuelle, sans modification",copyOption:"Copier le résumé de vérification",copied:"Résumé de vérification copié.",copyFallback:"Résumé préparé. Copiez le texte ci-dessous.",handoff:"Résumé de vérification des affectations",handoffLabel:"Résumé des affectations à copier",handoffScope:"Pour vérification uniquement. Achats, réservations et ordres de fabrication restent inchangés. Relancez l’analyse après toute modification des données ou des affectations.",planned:"Arrivée prévue sur la ligne d’achat",assumed:"Arrivée du scénario",material:"Matière",option:"Option",unreservedStock:"Stock actuel non réservé",confirmSupply:"Confirmer la disponibilité avec les achats et l’entrepôt",confirmStock:"Vérifier les changements de réservation avec le planificateur et l’entrepôt",noChecks:"Vérifier les arrivées réelles et le plan métier avant exécution."});

Object.assign(TEXT.zh,{priorityGuide:"如何设置订单优先级",priorityHelp:"方案读取制造单上的紧急（星标）优先级。请打开需要保护的制造单，由有权限的人员设置并保存，返回后重新分析并推荐方案。用料时间早晚与紧急优先级分别参与比较。",orderContext:"逐单用料与补齐时间"});
Object.assign(TEXT.en,{priorityGuide:"How to set order priority",priorityHelp:"Options use the urgent (star) priority recorded on manufacturing orders. Open the order to protect, have an authorized user set and save its priority, then return and run the analysis and recommendations again. Need time and urgency are compared separately.",orderContext:"Order needs and coverage times"});
Object.assign(TEXT.fr,{priorityGuide:"Comment définir la priorité",priorityHelp:"Les options utilisent la priorité urgente (étoile) enregistrée sur les ordres de fabrication. Ouvrez l’ordre à protéger, faites enregistrer sa priorité par une personne autorisée, puis relancez l’analyse et les recommandations. Date de besoin et urgence sont comparées séparément.",orderContext:"Besoins et dates de couverture par ordre"});

Object.assign(TEXT.zh,{moveTitle:"调 {quantity} {unit} 给 {order}",multiMoveTitle:"调整 {count} 张制造单的材料分配",priorityNames:"已标记高优先级",saveReview:"创建方案复核待办",followReview:"查看采购单复核进度",reviewHelp:"将本次方案保存到采购单待办，选择负责人和截止日期。核实后在待办反馈中记录采用或不采用的原因，再标记完成；业务数据变化后须重新分析。",reviewDraft:"方案待复核",reviewFailed:"无法打开复核待办，请稍后重试。",reviewDecision:"复核结论（待填写）：是否采用、原因、到货与预留核实结果。"});
Object.assign(TEXT.en,{moveTitle:"Move {quantity} {unit} to {order}",multiMoveTitle:"Reallocate material across {count} manufacturing orders",priorityNames:"Recorded high-priority orders",saveReview:"Create option review task",followReview:"View review progress on purchase",reviewHelp:"Save this option as a purchase activity, choose an owner and due date. Record the adoption decision and reason in activity feedback before marking it done. Analyze again if business data changes.",reviewDraft:"Option awaiting review",reviewFailed:"Could not open the review task. Please retry.",reviewDecision:"Review decision (to complete): adopt or decline, reason, arrival and reservation checks."});
Object.assign(TEXT.fr,{moveTitle:"Transférer {quantity} {unit} à {order}",multiMoveTitle:"Réaffecter la matière de {count} ordres",priorityNames:"Ordres de priorité élevée enregistrée",saveReview:"Créer une activité de vérification",followReview:"Suivre la vérification sur l’achat",reviewHelp:"Enregistrez cette option dans une activité de l’achat avec un responsable et une échéance. Notez la décision et son motif dans le retour avant de terminer l’activité. Relancez l’analyse si les données changent.",reviewDraft:"Option à vérifier",reviewFailed:"Impossible d’ouvrir l’activité. Réessayez.",reviewDecision:"Décision (à compléter) : accepter ou refuser, motif, vérifications des arrivées et réservations."});

const WORKFLOW_TEXT = {
 zh:{productionEvidence:'调料对已有生产准备的影响',reservationEvidence:'当前为该单预留 {reserved} {unit}；拟调走 {moved} {unit}，保留 {remaining} {unit}。',nativeReady:'原生制造概览：{state}（成品单位：{unit}）。',nativeUnknown:'原生备料状态尚未读取，请打开制造单核实。',readyCaveat:'这是当前备料信号。是否可以部分投产、调走材料损失多少，需生产确认。',keyBlocker:'采用前关键确认',conditionDetails:'查看完整采用条件',purchasing:'采购',warehouse:'仓储',production:'生产',plannerRole:'计划员',createRoleTask:'创建此项待办',roleTasks:'按职责协调',roleHelp:'每项单独选择负责人和截止日期，反馈核实结果；同一方案的事项通过原情景关联。',resume:'返回情景与核实进度',taskState:'核实结果（待填写）：结论、依据、下一步。待办完成表示本项核实完成，不表示已采用或执行调料。',decisionTask:'方案决策：记录采用或不采用、原因及执行进度。',resumeHelp:'打开共同方案并刷新核实进度，不调用 AI；业务数据变化后由计划员重新分析。',other_none:'物料清单核对：记录中无其他待备原料，请确认是否有漏记；本项不核实人员或设备。'},
 en:{productionEvidence:'Effect on existing production preparation',reservationEvidence:'Reserved for this order: {reserved} {unit}; proposed transfer: {moved} {unit}; retained: {remaining} {unit}.',nativeReady:'Native MO overview: {state} (finished-product unit: {unit}).',nativeUnknown:'Native readiness was not read. Open the manufacturing order to check.',readyCaveat:'This is current material readiness. Production must confirm partial production and the cost of moving material.',keyBlocker:'Key adoption check',conditionDetails:'All adoption conditions',purchasing:'Purchasing',warehouse:'Warehouse',production:'Production',plannerRole:'Planner',createRoleTask:'Create this review task',roleTasks:'Coordinate by responsibility',roleHelp:'Assign each task and due date separately. Record its findings; tasks link to the same scenario.',resume:'Return to this scenario and read fresh data',taskState:'Findings (to complete): decision, evidence and next step. Completing this task does not adopt or execute a transfer.',decisionTask:'Plan decision: record adoption or rejection, reason and execution progress.',resumeHelp:'Open the shared plan and refresh review progress without calling AI. Ask the planner to reanalyze after business data changes.',other_none:'Component list check: no other component is pending in records; confirm none is omitted. People and equipment are checked separately.'},
 fr:{productionEvidence:'Effet sur la préparation de fabrication',reservationEvidence:'Réservé pour cet ordre : {reserved} {unit} ; transfert prévu : {moved} {unit} ; conservé : {remaining} {unit}.',nativeReady:'Vue native de fabrication : {state} (unité du produit fini : {unit}).',nativeUnknown:'Disponibilité native non lue. Ouvrir l’ordre pour vérifier.',readyCaveat:'État actuel des matières. La production doit confirmer la fabrication partielle et la perte liée au transfert.',keyBlocker:'Vérification clé avant adoption',conditionDetails:'Toutes les conditions',purchasing:'Achats',warehouse:'Entrepôt',production:'Production',plannerRole:'Planification',createRoleTask:'Créer cette tâche de vérification',roleTasks:'Coordonner par responsabilité',roleHelp:'Choisir le responsable et l’échéance de chaque tâche. Les tâches renvoient au même scénario.',resume:'Revenir au scénario et relire les données',taskState:'Résultat à renseigner : décision, preuves et suite. Terminer la tâche ne valide ni n’exécute le transfert.',decisionTask:'Décision : adoption ou refus, motif et suivi d’exécution.',resumeHelp:'Le lien restaure le scénario et actualise les calculs et le suivi sans appel IA.',other_none:'Vérifier la liste des matières : aucun autre composant à préparer enregistré. Confirmer les omissions éventuelles ; ressources vérifiées séparément.'}
};
Object.assign(TEXT.zh,{aiNotRequested:'本次未调用 AI。以下为当前计算方案与核实进度；需要新解读时可点击 AI 推荐方案。'});
Object.assign(TEXT.en,{aiNotRequested:'AI was not called. Current calculated options and review progress are shown; request AI recommendations for a new interpretation.'});
Object.assign(TEXT.fr,{aiNotRequested:'Aucun appel IA effectué. Les options calculées et le suivi actuels sont affichés ; demandez une recommandation IA pour une nouvelle interprétation.'});

Object.assign(WORKFLOW_TEXT.zh, {
    partial_production:'生产：确认允许调走这批预留材料；若原单能部分投产，先评估并接受调走材料造成的损失。',
    other_none:'物料清单核对：确认未漏记其他所需原料；本项不核实人员或设备。',
    handoffNow:'当前处理状态',handoffNext:'下一步',handoffDetails:'附录：完整计算与核实记录',
    nextBlocked:'先解决以下未满足条件，获得明确反馈后再复核本方案；当前不要执行调料。',
    nextWaiting:'分派并完成尚未确认的目标，再决定是否采用；当前不要执行调料。',
    nextReady:'由业务负责人确认是否采用并安排执行；本报告没有执行调料。',
    nextUnavailable:'先刷新并核对完整核实记录，再判断方案是否可采用。'
});
Object.assign(WORKFLOW_TEXT.en, {
    partial_production:'Production: confirm that these reserved materials may be transferred. If the donor can start partial production, assess and accept the loss before allowing the transfer.',
    other_none:'Component list: confirm that no required component is omitted. People and equipment are checked separately.',
    handoffNow:'Current disposition',handoffNext:'Next step',handoffDetails:'Appendix: full calculations and reviews',
    nextBlocked:'Resolve the unmet requirements below and obtain explicit feedback before reviewing adoption. Do not execute the transfer now.',
    nextWaiting:'Assign and verify the outstanding targets before deciding on adoption. Do not execute the transfer now.',
    nextReady:'The business owner must confirm adoption and arrange execution; this report has not executed a transfer.',
    nextUnavailable:'Refresh and check the complete review records before assessing adoption.'
});
Object.assign(WORKFLOW_TEXT.fr, {
    partial_production:'Production : confirmer que les matières réservées peuvent être transférées. Si une fabrication partielle est possible pour le cédant, évaluer et accepter la perte avant le transfert.',
    other_none:'Liste des matières : confirmer qu’aucun composant requis n’est omis. Personnel et équipements vérifiés séparément.',
    handoffNow:'État actuel de décision',handoffNext:'Prochaine étape',handoffDetails:'Annexe : calculs et vérifications complets',
    nextBlocked:'Résoudre les conditions non remplies et obtenir un retour explicite avant de revoir l’adoption. Ne pas exécuter le transfert maintenant.',
    nextWaiting:'Attribuer et vérifier les objectifs restants avant de décider. Ne pas exécuter le transfert maintenant.',
    nextReady:'Le responsable métier doit confirmer l’adoption et organiser l’exécution ; ce rapport n’a exécuté aucun transfert.',
    nextUnavailable:'Actualiser et vérifier les retours complets avant d’évaluer l’adoption.'
});

Object.assign(TEXT.zh,{interrupted:"AI 请求中断，无法确认是否已计费，系统不会自动重发。再次点击 AI 推荐方案会发起新请求，可能再次计费。"});
Object.assign(TEXT.en,{interrupted:"AI request interrupted; billing is uncertain. No automatic retry. Clicking AI recommendations again starts a new potentially billable request."});
Object.assign(TEXT.fr,{interrupted:"Requête IA interrompue ; facturation inconnue. Aucun renvoi automatique. Un nouveau clic peut être facturé."});

export class ReallocationPanel extends Component {
    static template = "material_delay_impact.Reallocation";
    static props = owlApi.useProps ? undefined : ["orderId", "lineId", "arrival", "lang", "timezone", "originalSnapshot", "configured", "report?", "onRecommendation?", "resumeReview?", "shared?"];
    setup() {
        if (owlApi.useProps) this.props = owlApi.useProps();
        this.orm = this.env.services.orm;
        this.action = this.env.services.action;
        this.key = JSON.stringify([user.userId, user.context.allowed_company_ids || [], this.props.orderId,
            this.props.lineId, this.props.arrival, this.props.originalSnapshot, this.props.lang]);
        if (!memory.has(this.key)) {
            if (memory.size >= 8) memory.delete(memory.keys().next().value);
            memory.set(this.key, { data: { prepared: null, receiver: "", candidates: [], selected: "", quantity: "",
                plan: [], comparison: null, busy: false, error: "", ai: null, aiBusy: false, aiError: "", automatic:null,autoError:"",handoffText:"",handoffOption:"",copyStatus:"",copyManual:false }, listeners: new Set() });
        }
        this.entry = memory.get(this.key);
        if(this.props.shared)this.entry.data.automatic=clone(this.props.shared);
        this.state = useState(clone(this.entry.data));
        this.feedbackEditor = useState({id:null, outcome:'unknown', feedback:'', busy:false, error:''});
        this.listener = patch => Object.assign(this.state, clone(patch));
        this.reviews = useState({tasks:[],error:'',busy:false,truncated:false,freshness:'unknown',checkedAt:''});
        this.decisionEditors = useState({});
        onMounted(() => { this.entry.listeners.add(this.listener); this.listener(this.entry.data); this.notifyRecommendation(); if(this.props.resumeReview && !this.state.automatic)this.recommend(false); else this.refreshReviews(); });
        onWillUnmount(() => this.entry.listeners.delete(this.listener));
        this.checkOnReturn=()=>{if(this.state.automatic && !this.state.busy && !this.state.aiBusy && Date.now()-(this.lastFreshnessCheck || 0)>3000)this.refreshReviews();};
        onMounted(()=>window.addEventListener('focus',this.checkOnReturn));
        onWillUnmount(()=>window.removeEventListener('focus',this.checkOnReturn));
    }
    t(key) { return WORKFLOW_TEXT[this.props.lang]?.[key] || DECISION_TEXT[this.props.lang]?.[key] || TEXT[this.props.lang]?.[key] || DECISION_TEXT.en[key] || TEXT.en[key] || key; }
    patch(values) { Object.assign(this.entry.data, clone(values)); this.entry.listeners.forEach(fn => fn(values)); }
    number(value) { return new Intl.NumberFormat({zh:"zh-CN",en:"en-US",fr:"fr-FR"}[this.props.lang], {maximumFractionDigits:20}).format(value); }
    coverageDate(value, need, shortage, history=null) {
        const full=Date.parse(value), due=Date.parse(need);
        if((shortage===0 || typeof shortage==='string' && shortage.trim()!=='' && Number(shortage)===0) && Number.isFinite(full) && Number.isFinite(due) && full<=due)
            return ({zh:'用料时已满足',en:'Covered by need time',fr:'Couvert au moment du besoin'})[this.props.lang] || 'Covered by need time';
        return history ? this.historyDate(value,history) : this.date(value);
    }
    date(value) { return value ? luxon.DateTime.fromISO(value).setZone(this.props.timezone).toFormat("yyyy-MM-dd HH:mm") : this.t("unknown"); }
    name(ref) { return this.state.prepared?.report.rows.find(r => r.ref === ref)?.mo || ref; }
    source(ref) {
        const report = this.state.prepared?.report;
        const item = report?.evidence.find(r => r.ref === ref);
        if (item) return item.purchase ? `${item.purchase} / ${item.label}` : item.label;
        const owner = report?.rows.find(r => r.allocations.some(a => a.ref === ref && ref.includes(":reserved:")));
        return owner ? this.t("current").replace("{mo}", owner.mo) : ref;
    }
    get targets() { return this.state.prepared?.report.rows.filter(r => r.delayed_shortage > 0) || []; }
    get resultRows() {
        const comparison = this.state.comparison;
        return comparison ? comparison.rows.map(row => ({...row,
            before: this.state.prepared.report.rows.find(r => r.ref === row.ref),
            impact: comparison.impacts.find(r => r.ref === row.ref)})) : [];
    }
    hours(seconds) { return seconds == null || !Number.isFinite(Number(seconds)) ? this.t("unknown") : `${this.number(Number(seconds) / 3600)} ${this.t("hours")}`; }
    metricTone(before, after) {
        if (before == null || after == null) return "unknown";
        const a=Number(before), b=Number(after);
        if (!Number.isFinite(a) || !Number.isFinite(b)) return "unknown";
        return b<a ? "better" : b>a ? "worse" : "neutral";
    }
    metricChange(before, after) { return this.t({better:"decreased",worse:"increased",neutral:"stable",unknown:"unknown"}[this.metricTone(before,after)]); }
    valueTone(value) { return value == null || !Number.isFinite(Number(value)) ? "unknown" : Number(value)>0 ? "worse" : "better"; }
    dateTone(before,after) {
        if (!after) return "unknown";
        if (!before) return "better";
        return this.metricTone(luxon.DateTime.fromISO(before).toMillis(),luxon.DateTime.fromISO(after).toMillis());
    }
    autoName(ref) { return this.state.automatic?.report.rows.find(r=>r.ref===ref)?.mo || this.state.automatic?.report.evidence.find(r=>r.ref===ref)?.label || ref; }
    autoSource(ref) {
        const item=this.state.automatic?.report.evidence.find(r=>r.ref===ref);
        if(item)return [item.purchase,item.label].filter(Boolean).join(" / ");
        const source=this.state.automatic?.automatic.alternatives.flatMap(o=>o.comparison.source_balances).find(s=>s.ref===ref);
        if(source?.kind==="unreserved_stock")return this.t("unreservedStock");
        return source?.kind==="reserved_stock" ? this.t("current").replace("{mo}",this.autoName(ref.split(":reserved:")[1]||ref)) : ref;
    }
    autoRecord(ref) {
        if(this.props.shared)return null;
        const report=this.state.automatic?.report || this.props.report;
        const row=report?.rows.find(r=>r.ref===ref);
        const item=report?.evidence.find(r=>r.ref===ref && r.kind==="receipt" && r.model==="stock.picking");
        const id=row?.mo_id || item?.id;
        return Number.isSafeInteger(id) && id>0 ? {model:row?"mrp.production":"stock.picking",id} : null;
    }
    openAutoRecord(ref) {
        const record=this.autoRecord(ref);
        if(record && this.action)return this.action.doAction({type:"ir.actions.act_window",res_model:record.model,
            res_id:record.id,views:[[false,"form"]],target:"current"});
    }
    get priorityOrders() {
        const report=this.state.automatic?.report || this.props.report;
        return [...new Map((report?.rows || []).map(r=>[r.mo_id || r.mo || r.ref,r])).values()];
    }
    get noAdjustmentNeeded() {
        const report=this.state.automatic?.report || this.props.report;
        const covered=!!report?.rows.length && report.unfilled===0 && report.rows.every(row=>
            typeof row.delayed_shortage==="number" && Number.isFinite(row.delayed_shortage) && row.delayed_shortage===0 &&
            typeof row.unfilled==="number" && Number.isFinite(row.unfilled) && row.unfilled===0 &&
            row.full_at && luxon.DateTime.fromISO(row.full_at).isValid && luxon.DateTime.fromISO(row.need_at).isValid &&
            luxon.DateTime.fromISO(row.full_at).toMillis()<=luxon.DateTime.fromISO(row.need_at).toMillis());
        if(!covered)return false;
        const options=this.state.automatic?.automatic.alternatives;
        const zero=value=>typeof value!=="boolean" && value!==null && value!=="" && Number.isFinite(Number(value)) && Number(value)===0;
        return !options || (!!options.length && options.every(o=>!o.comparison.plan.transfers.length && zero(o.comparison.unfilled) &&
            o.comparison.rows.length===report.rows.length && o.comparison.rows.every(r=>zero(r.shortage_at_due) && zero(r.unfilled) &&
                r.full_at && luxon.DateTime.fromISO(r.full_at).isValid && luxon.DateTime.fromISO(r.need_at).isValid &&
                luxon.DateTime.fromISO(r.full_at).toMillis()<=luxon.DateTime.fromISO(r.need_at).toMillis())));
    }
    impactSummary(impact) {
        const unit=this.state.automatic.report.unit, parts=[];
        if(this.metricTone(impact.shortage_before,impact.shortage_after)!=="neutral")
            parts.push(`${this.t("shortage")}: ${this.number(impact.shortage_before)} → ${this.number(impact.shortage_after)} ${unit}`);
        if(impact.full_at_before!==impact.full_at_after)
            parts.push(`${this.t("full")}: ${this.coverageDate(impact.full_at_before,this.state.automatic.report.rows.find(r=>r.ref===impact.ref)?.need_at,impact.shortage_before)} → ${this.coverageDate(impact.full_at_after,this.state.automatic.report.rows.find(r=>r.ref===impact.ref)?.need_at,impact.shortage_after)}`);
        if(this.metricTone(impact.unfilled_before,impact.unfilled_after)!=="neutral")
            parts.push(`${this.t("final")}: ${impact.unfilled_before==null?this.t("unknown"):this.number(impact.unfilled_before)} → ${impact.unfilled_after==null?this.t("unknown"):this.number(impact.unfilled_after)} ${unit}`);
        return parts.join(" · ");
    }
    optionTitle(option) {
        const moves=option.comparison.plan.transfers;
        if(!moves.length)return this.t("keep");
        const receivers=[...new Set(moves.map(m=>m.receiver_ref))];
        if(receivers.length===1 && moves.length===1)return this.phrase("moveTitle",{
            quantity:this.number(moves[0].quantity),unit:this.state.automatic.report.unit,order:this.autoName(receivers[0])});
        const orders=new Set(moves.flatMap(m=>[m.receiver_ref,m.donor_ref]).filter(ref=>this.state.automatic.report.rows.some(r=>r.ref===ref)));
        return this.phrase("multiMoveTitle",{count:this.number(orders.size)});
    }
    get markedPriorityNames() {
        return (this.state.automatic?.automatic.priority_refs || []).map(ref=>this.autoName(ref)).join(" · ");
    }
    decisionStatus(option) {
        const status=option.decision_support?.status;
        return this.t(status === 'keep' ? 'keepDecision' : status || 'decisionUnavailable');
    }
    coordinationText(item) {
        const unit=this.state.automatic.report.unit;
        const parts=[`${this.t(item.owner)} · ${this.t(item.kind)}`,this.autoName(item.ref),
            `${this.number(item.quantity)} ${unit}`,`${this.t('by')}: ${this.date(item.deadline)}`];
        if(item.source_ref)parts.push(this.autoSource(item.source_ref));
        if(item.donor_ref)parts.push(`${this.autoName(item.donor_ref)} → ${this.autoName(item.ref)}`);
        if(item.available_at)parts.push(`${this.t('scenarioAvailable')}: ${this.date(item.available_at)}`);
        if(item.late)parts.push(this.t('lateSupply'));
        if(item.kind==='gap_target')parts.push(this.phrase('gapSplit',{late:this.number(item.late_quantity),remaining:this.number(item.unfilled),unit}));
        if(item.kind==='additional_supply')parts.push(this.t('unknownSupplier'));
        if(['expedite','additional_supply'].includes(item.kind))parts.push(this.t('confirmOnly'));
        return parts.join(' · ');
    }
    productionEvidenceText(item) {
        return this.phrase('reservationEvidence',{reserved:this.number(item.reserved),moved:this.number(item.moved),remaining:this.number(item.remaining),unit:this.state.automatic.report.unit});
    }
    nativeReadyText(item) {
        return item.native_readiness ? this.phrase('nativeReady',{state:item.native_readiness,unit:item.production_unit || this.t('unknown')}) : this.t('nativeUnknown');
    }
    handoffLabel(mode='summary') {
        const labels={zh:{summary:'交接摘要',full:'完整记录'},en:{summary:'Handoff summary',full:'Full record'},fr:{summary:'Synthèse de passation',full:'Dossier complet'}};
        return (labels[this.props.lang] || labels.en)[mode];
    }
    copyLabel(mode) {
        return ({zh:'复制',en:'Copy ',fr:'Copier '}[this.props.lang] || 'Copy ')+this.handoffLabel(mode);
    }
    copyMessage(mode,success) {
        const suffix={zh:success?'已复制。':'未能自动复制，请在下方文本框中手动复制。',en:success?' copied.':' could not be copied automatically. Copy the text below.',fr:success?' copié.':' non copié automatiquement. Copiez le texte ci-dessous.'};
        return this.handoffLabel(mode)+(suffix[this.props.lang] || suffix.en);
    }
    conditionReview(option,item) {
        // Ref alone is insufficient: production, capacity and warehouse are separate goals.
        const target=(option.review_targets || []).find(t=>[...(t.conditions || []),...(t.actions || [])].some(c=>c.kind===item.kind && c.ref===item.ref && c.source_ref===item.source_ref && c.donor_ref===item.donor_ref));
        return target && this.currentTargetReview(option,target);
    }
    reviewSubject(option,task) {
        const target=(option.review_targets || []).find(t=>t.key===task.target_key);
        const item=target?.conditions?.[0] || target?.actions?.[0];
        return item ? `${this.t(target.role)} · ${this.autoName(item.ref)} · ${this.rt('done')} · ${this.ux(this.outcome(task))}` : this.ux(this.outcome(task));
    }
    itemReviewText(option,item,compact=false) {
        const task=this.conditionReview(option,item),ref=this.autoName(item.ref);
        if(this.reviews?.error || this.reviews?.truncated)return `${ref} · ${this.ux('unavailable')}`;
        if(task?.done)return `${ref} · ${this.rt('done')} · ${this.ux(this.outcome(task))}${compact ? '' : ' · '+(task.feedback || this.rt('noFeedback'))}`;
        return `${ref} · ${this.t(item.kind)}`;
    }
    productionReviewText(option,item,compact=false) {
        const condition=(option.decision_support?.conditions || []).find(c=>c.ref===item.ref && c.kind==='partial_production');
        return condition ? this.itemReviewText(option,condition,compact) : this.t('readyCaveat');
    }
    keyBlocker(option,compact=false) {
        const items=option.decision_support?.conditions || [];
        const item=items.find(c=>c.kind==='priority_conflict') || items.find(c=>c.kind==='partial_production') || items.find(c=>c.kind==='accept_harm');
        return item ? this.itemReviewText(option,item,compact) : this.reviewAssessment(option).text;
    }
    checkReviewText(option,check,ref,compact=false) {
        const kinds={confirm_arrival:['confirm_receipt','expedite'],confirm_reservation:['release_reservation'],review_priority:['priority_conflict','accept_harm'],find_additional_supply:['additional_supply']};
        const targets=(option.review_targets || []).filter(t=>[...(t.conditions || []),...(t.actions || [])].some(c=>(kinds[check.kind] || []).includes(c.kind) && (c.ref===ref || c.source_ref===ref)));
        if(this.reviews?.error || this.reviews?.truncated)return `${this.autoName(ref)} · ${this.ux('unavailable')}`;
        const tasks=targets.map(t=>this.currentTargetReview(option,t));
        if(tasks.length && tasks.every(t=>t?.done))return `${this.autoName(ref)} · ${this.rt('done')} · `+tasks.map(t=>`${this.ux(this.outcome(t))}${compact ? '' : ' · '+(t.feedback || this.rt('noFeedback'))}`).join(' · ');
        return `${this.t(check.kind)}: ${this.autoName(ref)}`;
    }
    coordinationGroups(option) {
        const groups=new Map();
        const get=role=>{if(!groups.has(role))groups.set(role,{role,actions:[],conditions:[]});return groups.get(role);};
        for(const a of option.decision_support?.actions || []){
            if(a.kind==='gap_target')continue;
            get(a.kind==='coordinate_transfer'?'warehouse':'purchasing').actions.push(a);
        }
        for(const c of option.decision_support?.conditions || []){
            get(c.kind==='release_reservation'?'warehouse':['accept_harm','priority_conflict'].includes(c.kind)?'plannerRole':'production').conditions.push(c);
        }
        return [...groups.values()].map(g=>({...g,targets:(option.review_targets || []).filter(t=>t.role===g.role)}));
    }
    rt(key) {
        const labels={zh:{progress:'核实进度与反馈',refresh:'刷新进度',pending:'待核实',done:'核实完成',stale:'历史记录 · 需重新核实',none:'尚未创建核实待办',owner:'负责人',due:'截止日期',feedback:'反馈',noFeedback:'尚未记录反馈',open:'查看 / 反馈',create:'分派此目标',again:'重新核实此目标',failed:'核实进度读取失败，请重试。',limit:'仅显示最近200条可访问的核实记录。',scope:'完成仅表示核实结束；是否采用和业务执行需另行确认。',history:'历史假设到货',decision:'方案决策',updated:'更新',targetHelp:'每个目标可单独选择负责人、截止日期并完成。',newTask:'新建待办后，请点击“查看 / 反馈”记录结论并完成。'},
        en:{progress:'Review progress and feedback',refresh:'Refresh progress',pending:'Pending',done:'Verified',stale:'Historical — verify again',none:'No review tasks yet',owner:'Owner',due:'Due',feedback:'Feedback',noFeedback:'No feedback recorded',open:'View / feedback',create:'Assign this target',again:'Verify target again',failed:'Could not load review progress. Retry.',limit:'Showing the latest 200 accessible reviews.',scope:'Completion means verification only, not adoption or execution.',history:'Historical assumed arrival',decision:'Option decision',updated:'Updated',targetHelp:'Assign an owner and deadline and complete each target independently.',newTask:'After saving, use View / feedback to record the conclusion and complete.'},
        fr:{progress:'Suivi et retours',refresh:'Actualiser',pending:'À vérifier',done:'Vérifié',stale:'Historique — à revérifier',none:'Aucune vérification créée',owner:'Responsable',due:'Échéance',feedback:'Retour',noFeedback:'Aucun retour',open:'Voir / répondre',create:'Attribuer cet objectif',again:'Revérifier cet objectif',failed:'Impossible de charger le suivi.',limit:'Les 200 dernières vérifications accessibles sont affichées.',scope:'Terminé signifie vérifié, pas adopté ni exécuté.',history:'Arrivée supposée historique',decision:'Décision',updated:'Mis à jour',targetHelp:'Chaque objectif a son responsable, son échéance et sa clôture.',newTask:'Après enregistrement, ouvrez Voir / répondre pour conclure.'}};
        return (labels[this.props.lang] || labels.en)[key];
    }
    async refreshReviews() {
        if(this.reviewLoading)return this.reviewLoading;
        if(!this.reviews)return;
        this.reviews.busy=true;this.reviews.error='';
        this.lastFreshnessCheck=Date.now();
        this.reviewLoading=(async()=>{
            try {if(!this.props.shared)await this.orm.call('purchase.order','mdic_publish_reviews',[[this.props.orderId],this.props.lineId,this.props.arrival]);
                const result=await this.orm.call('purchase.order',this.props.shared?'mdic_shared_progress':'mdic_review_progress',[[this.props.orderId],this.props.lineId,...(this.props.shared?[this.props.arrival]:[this.props.arrival,this.state.automatic?.review_revision])]);
                this.reviews.tasks=result.tasks;this.reviews.truncated=result.truncated;
                this.reviews.freshness=result.freshness || 'unknown';this.reviews.checkedAt=new Date().toLocaleTimeString();
            }catch(_){this.reviews.error=this.rt('failed');this.reviews.freshness='unknown';}
            finally{this.reviews.busy=false;}
        })();
        try{await this.reviewLoading;}finally{this.reviewLoading=null;}
    }
    ux(key) {
        const labels={
          zh:{outcome:'本项安排能否落实',unknown:'待确认',met:'本项安排可落实',not_met:'本项安排不可落实',draft:'未完成核实',unassigned:'未分派',summary:'采用前核实',blocked:'存在未满足条件，暂不建议采用',waiting:'仍有目标待核实或结论待确认',ready:'已列目标条件均满足，仍需确认是否采用',unavailable:'核实记录未完整读取，不能据此判断条件已满足',history:'历史核实记录',other:'方案决策与其他记录',counts:'已核实 {done}/{total}',copyUnavailable:'最新核实进度读取失败。以下历史读取记录仅供参考，不代表当前结论。',short:'简要反馈',more:'完整反馈',loaded:'核实进度读取时间',draftOutcome:'暂存结论',noTargets:'没有独立核实目标，仍需人工复核'},
          en:{outcome:'Can this arrangement be carried out?',unknown:'To confirm',met:'Arrangement feasible',not_met:'Arrangement not feasible',draft:'Verification pending',unassigned:'Unassigned',summary:'Adoption checks',blocked:'Conditions are not met; adoption is not recommended yet',waiting:'Some targets or conclusions still need verification',ready:'Listed target conditions are met; adoption still needs confirmation',unavailable:'Review records are incomplete; conditions cannot be considered met',history:'Historical reviews',other:'Option decision and other records',counts:'Verified {done}/{total}',copyUnavailable:'Latest review progress could not be loaded. Previously loaded records below are historical, not current conclusions.',short:'Feedback',more:'Full feedback',loaded:'Review progress read at',draftOutcome:'Draft outcome',noTargets:'No separate review targets; human review is still required'},
          fr:{outcome:'Cette disposition est-elle réalisable ?',unknown:'À confirmer',met:'Disposition réalisable',not_met:'Disposition non réalisable',draft:'Vérification en cours',unassigned:'Non attribué',summary:'Vérifications avant adoption',blocked:'Conditions non remplies ; adoption déconseillée pour le moment',waiting:'Des objectifs ou conclusions restent à vérifier',ready:'Conditions listées remplies ; adoption à confirmer',unavailable:'Suivi incomplet ; les conditions ne peuvent être considérées remplies',history:'Vérifications historiques',other:'Décision et autres retours',counts:'Vérifiés {done}/{total}',copyUnavailable:'Impossible de charger le suivi récent. Les retours ci-dessous sont historiques, pas des conclusions actuelles.',short:'Retour',more:'Retour complet',loaded:'Suivi lu le',draftOutcome:'Conclusion provisoire',noTargets:'Aucun objectif distinct ; vérification humaine requise'}};
        return (labels[this.props.lang] || labels.en)[key];
    }
    decisionText(key) {
        const editing={zh:{edit:'更改取舍',cancel:'取消更改'},en:{edit:'Change decision',cancel:'Cancel changes'},fr:{edit:'Modifier la décision',cancel:'Annuler les modifications'}};
        if(editing[this.props.lang]?.[key] || editing.en[key])return (editing[this.props.lang] || editing.en)[key];
        const text={zh:{title:'方案取舍',none:'尚未记录取舍',adopt:'决定采用',reject:'不采用',defer:'暂缓决定',save:'保存取舍',reason:'取舍原因',help:'记录决定不会执行调料或修改制造单。采用前须完成本方案各项核实。',failed:'保存失败，请检查核实状态或重新读取情景。'},en:{title:'Option decision',none:'No decision recorded',adopt:'Adopt',reject:'Do not adopt',defer:'Defer decision',save:'Save decision',reason:'Decision reason',help:'Recording a decision does not execute transfers or change manufacturing orders. Complete the option checks before adopting.',failed:'Could not save. Check review status or reread the scenario.'},fr:{title:'Décision sur l’option',none:'Aucune décision enregistrée',adopt:'Adopter',reject:'Ne pas adopter',defer:'Différer',save:'Enregistrer la décision',reason:'Motif de la décision',help:'Enregistrer ne transfère pas la matière et ne modifie pas les ordres. Terminez les vérifications avant adoption.',failed:'Échec : vérifiez le suivi ou relisez le scénario.'}};
        return (text[this.props.lang] || text.en)[key] || key;
    }
    currentDecision(option) {
        return this.optionReviews(option).filter(t=>t.done && t.decision && !this.reviewStale(t)).sort((a,b)=>b.id-a.id)[0];
    }
    decisionEditorKey(option) { return `${this.state.automatic.review_revision}:${option.review_key}`; }
    decisionDraft(option) {
        const key=this.decisionEditorKey(option);
        if(!this.decisionEditors[key]) {
            const current=this.currentDecision(option);
            this.decisionEditors[key]={editing:false,choice:current?.decision || 'defer',reason:current?.feedback || ''};
        }
        return this.decisionEditors[key];
    }
    editDecision(option) {
        const current=this.currentDecision(option);
        this.decisionEditors[this.decisionEditorKey(option)]={editing:true,choice:current?.decision || 'defer',reason:current?.feedback || ''};
        this.patch({decisionError:null});
    }
    cancelDecision(option) {
        delete this.decisionEditors[this.decisionEditorKey(option)];
        this.patch({decisionError:null});
    }
    decisionNext(choice) {
        const text={zh:{reject:'本方案已记录为不采用，请继续评估其他方案；若改变取舍，请记录新的决定和原因。',defer:'本方案暂缓决定，请跟进未决事项后再记录取舍。',adopt:'已记录采用决定，请按业务流程安排后续执行；本记录不会执行调料。'},en:{reject:'This option was rejected. Evaluate other options; record a new decision and reason if the choice changes.',defer:'Decision deferred. Follow up outstanding matters before deciding.',adopt:'Adoption recorded. Arrange execution through the business process; this record executes no transfer.'},fr:{reject:'Option non retenue. Évaluez les autres options ; consignez toute nouvelle décision et son motif.',defer:'Décision différée. Suivez les points en attente avant de décider.',adopt:'Adoption enregistrée. Organisez l’exécution selon le processus métier ; cet enregistrement n’effectue aucun transfert.'}};
        return (text[this.props.lang] || text.en)[choice];
    }
    async recordDecision(option,event) {
        event.preventDefault();
        if(this.decisionSaving)return;
        const form=event.currentTarget, data=new FormData(form);
        this.decisionSaving=true;
        try {
            await this.orm.call('purchase.order','mdic_record_decision',[[this.props.orderId],this.props.lineId,this.props.arrival,option.review_key,this.state.automatic.review_revision,data.get('choice'),data.get('reason'),this.props.timezone]);
            this.patch({decisionError:null});await this.refreshReviews();
            if(!this.reviews.error)this.cancelDecision(option);
        }catch(error){this.patch({decisionError:{option:option.id,text:error?.data?.message || this.decisionText('failed')}});}
        finally{this.decisionSaving=false;}
    }
    outcome(task) {return ['met','not_met'].includes(task?.outcome) ? task.outcome : 'unknown';}
    reviewTone(task) {return this.reviewStale(task) || !task.done ? 'secondary' : this.outcome(task)==='not_met' ? 'danger' : this.outcome(task)==='met' ? 'success' : 'warning text-dark';}
    reviewTime(value) {return value ? this.date(value.replace(' ','T')+'Z') : this.t('unknown');}
    targetReviews(option,target) {return this.optionReviews(option).filter(t=>t.target_key===target.key);}
    groupProgress(option,group) {return this.ux('counts').replace('{done}',group.targets.filter(t=>this.currentTargetReview(option,t)?.done).length).replace('{total}',group.targets.length);}
    focusText(key) {return ({zh:{mine:'分派给我的事项',all:'本职责全部事项',unassigned:'未分派',open:'定位到本项',none:'本方案没有分派给你的核实事项'},en:{mine:'My assigned reviews',all:'All reviews for this role',unassigned:'Unassigned',open:'Go to this review',none:'No review in this option is assigned to you'},fr:{mine:'Mes vérifications attribuées',all:'Toutes les vérifications de ce rôle',unassigned:'Non attribuées',open:'Accéder à cette vérification',none:'Aucune vérification de cette option ne vous est attribuée'}})[this.props.lang][key];}
    myTargets(option) {return (option.review_targets || []).filter(t=>this.currentTargetReview(option,t)?.assigned_to_me);}
    myProgress(option) {const targets=this.myTargets(option);return this.groupProgress(option,{targets});}
    unassignedCount(option,group) {return group.targets.filter(t=>!this.currentTargetReview(option,t)).length;}
    focusReview(event,target) {
        const card=event.currentTarget.closest('article');
        const node=[...card.querySelectorAll('.mdic-review-target')].find(n=>n.dataset.targetKey===target.key);
        if(!node)return;
        const group=node.closest('details');if(group)group.open=true;
        node.scrollIntoView({behavior:'smooth',block:'center'});node.focus({preventScroll:true});
    }
    reviewAssessment(option) {
        if(this.factsOutdated())return {tone:'warning',text:this.freshnessText(),blocked:[]};
        const targets=option.review_targets || [],current=targets.map(t=>this.currentTargetReview(option,t));
        const blocked=current.filter(t=>t?.done && this.outcome(t)==='not_met');
        if(blocked.length)return {tone:'danger',text:this.ux('blocked'),blocked};
        if(this.reviews?.error || this.reviews?.truncated)return {tone:'warning',text:this.ux('unavailable'),blocked:[]};
        if(!targets.length)return {tone:'secondary',text:this.ux('noTargets'),blocked:[]};
        const all=current.every(t=>t?.done && this.outcome(t)==='met');
        return {tone:all?'success':'warning',text:this.ux(all?'ready':'waiting'),blocked:[]};
    }
    extraReviews(option) {const keys=new Set((option.review_targets || []).map(t=>t.key));return this.optionReviews(option).filter(t=>!keys.has(t.target_key));}
    reviewHandoff(option) {
        const text=[this.rt('progress'),this.reviewAssessment(option).text];
        if(this.reviews?.error)text.push(this.ux('copyUnavailable'));
        if(this.reviews?.truncated)text.push(this.rt('limit'));
        const append=(task)=>{
            text.push(task.summary || this.rt('decision'));
            text.push(this.reviewStale(task)?`${this.rt('stale')} · ${this.rt('history')}: ${this.reviewTime(task.arrival)}`:this.rt(task.done?'done':'pending'));
            text.push(`${this.rt('owner')}: ${task.owner || '—'} · ${this.rt('due')}: ${task.due || '—'}`);
            text.push(task.decision ? `${this.decisionText('title')}: ${this.decisionText(task.decision)}` : `${this.ux(task.done?'outcome':'draftOutcome')}: ${this.ux(this.outcome(task))}`);
            text.push(`${this.rt('feedback')}: ${task.feedback || this.rt('noFeedback')}`,`${this.rt('updated')}: ${this.reviewTime(task.updated)}`);
        };
        for(const target of option.review_targets || []){
            const task=this.currentTargetReview(option,target);
            if(task)append(task);
            else {const item=target.actions[0] || target.conditions[0];text.push(`${this.t(target.role)} · ${this.autoName(item.ref)} · ${this.t(item.kind)} · ${this.ux('unassigned')}`);}
        }
        const historical=this.optionReviews(option).filter(t=>this.reviewStale(t));
        if(historical.length){text.push(this.ux('history'));historical.forEach(append);}
        const extra=this.extraReviews(option).filter(t=>!this.reviewStale(t));
        if(extra.length){text.push(this.ux('other'));extra.forEach(append);}
        return text;
    }
    optionReviews(option) { return (this.reviews?.tasks || []).filter(t=>t.option_key===option.review_key); }
    factsOutdated() {return ['changed','unknown'].includes(this.reviews?.freshness);}
    freshnessText(key) {
        const copy={zh:{changed:'相关业务记录已变化。当前方案与旧反馈仅供追溯，请计划员重新读取并计算；到货、库存预留和受损订单的核实结论须按新方案重新确认。',unknown:'暂时无法确认方案是否仍适用。旧反馈保留为历史依据，请计划员重新读取后核实，暂勿据此采用。',unchanged:'截至本次检查，未发现相关数据变化。已核实反馈继续保留；这不代表实际到货或方案已执行。',refresh:'检查数据与核实进度',recalculate:'重新计算方案（不调用 AI）'},en:{changed:'Related business records changed. This plan and its feedback are historical. Ask the planner to recalculate and reconfirm arrivals, reservations and affected orders against the new plan.',unknown:'Plan freshness cannot be confirmed. Keep previous feedback as history; ask the planner to reread before adopting.',unchanged:'No related changes found at this check. Verified feedback is retained; this does not confirm actual receipt or execution.',refresh:'Check data and review progress',recalculate:'Recalculate options (no AI call)'},fr:{changed:'Des données liées ont changé. Ce plan et ses retours sont historiques. Le planificateur doit recalculer puis faire revérifier les arrivées, réservations et ordres affectés.',unknown:'Actualité du plan non confirmée. Conservez les retours comme historique et demandez une nouvelle lecture avant adoption.',unchanged:'Aucun changement lié détecté lors de ce contrôle. Les retours restent conservés ; réception et exécution ne sont pas confirmées.',refresh:'Vérifier les données et le suivi',recalculate:'Recalculer les options (sans appel IA)'}};
        return (copy[this.props.lang] || copy.en)[key || this.reviews?.freshness || 'unknown'];
    }
    reviewStale(task) { return this.factsOutdated() || !!task.facts_stale || task.revision!==this.state.automatic?.review_revision; }
    currentTargetReview(option,target) {
        return this.optionReviews(option).find(t=>t.target_key===target.key && !this.reviewStale(t));
    }
    canOpenReview(task) { return !this.props.shared || (!this.factsOutdated() && !!task?.can_feedback); }
    feedbackText(key) {return ({zh:{save:'保存反馈并完成核实',cancel:'取消',help:'只完成分派给自己的核实事项，不会采用方案或执行调料。'},en:{save:'Save feedback and complete review',cancel:'Cancel',help:'Complete your assigned review only. This does not adopt or execute the option.'},fr:{save:'Enregistrer et terminer la vérification',cancel:'Annuler',help:'Terminez uniquement votre vérification. Cela n’adopte ni n’exécute l’option.'}})[this.props.lang][key];}
    async submitSharedFeedback(event) {
        event.preventDefault(); const e=this.feedbackEditor;if(e.busy)return;e.busy=true;e.error='';
        try {await this.orm.call('purchase.order','mdic_shared_feedback',[[this.props.orderId],this.props.lineId,this.props.arrival,e.id,e.outcome,e.feedback]);e.id=null;await this.refreshReviews();}
        catch(error){e.error=error.data?.message || this.rt('failed');}finally{e.busy=false;}
    }
    async openReview(task) {
        if(this.props.shared){if(task.can_feedback)Object.assign(this.feedbackEditor,{id:task.id,outcome:task.outcome || 'unknown',feedback:task.feedback || '',error:''});return;}
        try {const action=await this.orm.call('purchase.order','mdic_review_open',[[this.props.orderId],this.props.lineId,task.id]);
            await this.action.doAction(action,{onClose:()=>this.refreshReviews()});
        }catch(_){this.reviews.error=this.rt('failed');}
    }
    resumeURL() {
        const q=new URLSearchParams({active_id:String(this.props.orderId),mdic_line:String(this.props.lineId),mdic_arrival:this.props.arrival,mdic_tz:this.props.timezone});
        return `/odoo/action-material_delay_impact?${q.toString()}`;
    }
    async saveReview(option, group=null) {
        if(this.reviewOpening)return;
        this.reviewOpening=true;
        try {
            const existing=group?.key && this.currentTargetReview(option,group);
            if(existing){await this.openReview(existing);return;}
            if(this.props.shared)return;
            const reviewContext=await this.orm.call('purchase.order','mdic_review_context',[[this.props.orderId],this.props.lineId,this.props.arrival,
                option.review_key,group?.key || 'decision',this.state.automatic.review_revision]);
            const report=this.state.automatic.report;
            const lines=[group?this.t('taskState'):this.t('decisionTask'),
                `${this.t('option')}: ${this.optionTitle(option)}`,
                `${this.t('material')}: ${report.product}`,
                `${this.t('read')}: ${this.date(report.taken_at)}`,
                `${this.t('assumed')}: ${this.date(report.assumed_at)}`,this.autoSummary(option)];
            if(group){
                for(const c of group.conditions)lines.push(`${this.autoName(c.ref)}: ${this.t(c.kind)}`);
                for(const a of group.actions)lines.push(this.coordinationText(a));
                if(group.role==='production')for(const item of (option.decision_support?.production_evidence || []).filter(e=>group.conditions.some(c=>c.kind==='partial_production' && c.ref===e.ref)))lines.push(`${this.autoName(item.ref)}: ${this.productionEvidenceText(item)} ${this.nativeReadyText(item)} ${this.t('readyCaveat')}`);
            }else{
                lines.push(...option.comparison.impacts.filter(i=>i.change!=='unchanged').map(i=>`${this.autoName(i.ref)}: ${this.impactSummary(i)}`),this.keyBlocker(option),this.t('taskState'));
            }
            const escape=text=>String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
            const refs=new Set(group ? [...group.conditions.map(c=>c.ref),...group.actions.flatMap(a=>[a.ref,a.source_ref,a.donor_ref]).filter(Boolean)] : option.comparison.impacts.filter(i=>i.change!=='unchanged').map(i=>i.ref));
            const links=[...refs].map(ref=>({ref,record:this.autoRecord(ref)})).filter(x=>x.record).map(({ref,record})=>`<p><a href="/odoo/${record.model}/${record.id}">${escape(this.autoName(ref))}</a></p>`).join('');
            const note=lines.map(line=>`<p>${escape(line)}</p>`).join('')+links+`<p><a href="${escape(this.resumeURL())}">${escape(this.t('resume'))}</a></p><p>${escape(this.t('resumeHelp'))}</p>`;
            const dates=(group ? [...group.actions.map(a=>a.deadline),...group.conditions.map(c=>report.rows.find(r=>r.ref===c.ref)?.need_at)] : report.rows.map(r=>r.need_at)).filter(Boolean).map(d=>luxon.DateTime.fromISO(d).setZone(this.props.timezone)).filter(d=>d.isValid);
            const due=dates.sort((a,b)=>a.toMillis()-b.toMillis())[0]?.toISODate();
            await this.action.doAction({type:'ir.actions.act_window',res_model:'mail.activity.schedule',views:[[false,'form']],target:'new',
                context:{...reviewContext,active_model:'purchase.order',active_id:this.props.orderId,active_ids:[this.props.orderId],
                    default_summary:`${group?this.t(group.role):this.t('reviewDraft')} · ${this.optionTitle(option)}${group ? ' · '+this.autoName((group.actions[0] || group.conditions[0]).ref)+' · '+this.t((group.actions[0] || group.conditions[0]).kind) : ''}`,
                    ...(due?{default_date_deadline:due}:{}),default_note:note}},{onClose:()=>this.refreshReviews()});
        }catch(_){this.patch({autoError:this.t('reviewFailed')});}
        finally{this.reviewOpening=false;}
    }
    openReviews() {
        return this.action.doAction({type:"ir.actions.act_window",res_model:"purchase.order",res_id:this.props.orderId,views:[[false,"form"]],target:"current"});
    }
    handoffSummary(option) {
        const report=this.state.automatic.report;
        const assessment=this.reviewAssessment(option);
        const unavailable=Boolean(this.reviews?.error || this.reviews?.truncated);
        const text=[`${this.t("handoff")} · ${report.order}`,
            `${this.t('handoffNow')}: ${unavailable?this.ux('unavailable'):assessment.text}`,
            `${this.t('option')}: ${this.optionTitle(option)}`];
        const decision=this.currentDecision(option);
        if(decision)text.push(`${this.decisionText('title')}: ${this.decisionText(decision.decision)} · ${decision.feedback} · ${decision.owner}`);
        if(unavailable)text.push(this.ux('copyUnavailable'));
        // Current blockers must reach the receiving colleague before any benefits.
        if(!unavailable)for(const task of assessment.blocked){
            text.push(`${this.ux(this.outcome(task))} · ${this.rt('feedback')}: ${task.feedback || this.rt('noFeedback')}`,
                `${this.rt('owner')}: ${task.owner || '—'} · ${this.rt('due')}: ${task.due || '—'}`);
        }
        const next=unavailable?'nextUnavailable':assessment.blocked.length?'nextBlocked':assessment.tone==='success'?'nextReady':'nextWaiting';
        text.push(`${this.t('handoffNext')}: ${!unavailable && decision ? this.decisionNext(decision.decision) : this.t(next)}`,
            `${this.t('assumed')}: ${this.date(report.assumed_at)} (${this.props.timezone})`,
            `${this.t('material')}: ${report.product} · ${report.unit}`,this.t('handoffScope'));
        return text.join('\n');
    }
    handoffText(option) {
        const report=this.state.automatic.report;
        const text=[this.handoffSummary(option),'',this.t('handoffDetails'),this.autoSummary(option)];
        text.push(`${this.t("material")}: ${report.product} · ${report.unit}`,
            `${this.t("read")}: ${this.date(report.taken_at)} (${this.props.timezone})`,
            `${this.t("planned")}: ${this.date(report.planned_at)}`,`${this.t("assumed")}: ${this.date(report.assumed_at)}`,
            `${this.t("option")}: ${this.optionTitle(option)} · ${option.strategies.map(s=>this.t(s)).join(" · ")}`,this.t("benefits"));
        text.push(this.t("orderContext"),...option.comparison.rows.map(row=>this.handoffOrder(row,option)));
        text.push(this.t("steps"));
        const transfers=option.comparison.plan.transfers;
        text.push(...(transfers.length?transfers.map(t=>`${this.autoSource(t.source_ref)} · ${this.autoName(t.donor_ref)} → ${this.autoName(t.receiver_ref)} · ${this.number(t.quantity)} ${report.unit}`):[this.t("keep")]));
        text.push(this.t('adoption'),this.reviewAssessment(option).text);
        for(const condition of option.decision_support?.conditions || [])text.push(this.itemReviewText(option,condition));
        for(const item of option.decision_support?.production_evidence || [])text.push(`${this.autoName(item.ref)}: ${this.productionEvidenceText(item)} ${this.nativeReadyText(item)} ${this.productionReviewText(option,item)}`);
        text.push(this.t('coordination'),this.t('decisionScope'));
        for(const item of option.decision_support?.actions || [])text.push(this.conditionReview(option,item)?.done ? this.itemReviewText(option,item) : this.coordinationText(item));
        return [...text,...this.reviewHandoff(option),this.t("caveat"),this.t("handoffScope")].join("\n");
    }
    handoffOrder(row,option) {
        const impact=option.comparison.impacts.find(i=>i.ref===row.ref),unit=this.state.automatic.report.unit;
        const number=value=>value==null || typeof value==="boolean" || value==="" || !Number.isFinite(Number(value)) ? this.t("unknown") : this.number(value);
        return [`${this.autoName(row.ref)} · ${this.t(impact?.change || "unknown")}`,
            `${this.t("need")}: ${this.date(row.need_at)}`,
            `${this.t("shortage")}: ${number(impact?.shortage_before)} → ${number(row.shortage_at_due)} ${unit}`,
            `${this.t("full")}: ${this.coverageDate(impact?.full_at_before,row.need_at,impact?.shortage_before)} → ${this.coverageDate(row.full_at,row.need_at,row.shortage_at_due)}`,
            `${this.t("final")}: ${number(impact?.unfilled_before)} → ${number(row.unfilled)} ${unit}`].join(" · ");
    }
    notifyRecommendation() {
        const value=this.state.automatic;
        if(!value || !this.props.onRecommendation)return;
        // History keeps locally calculated facts, never provider narrative or callbacks.
        this.props.onRecommendation({taken_at:value.report.taken_at,options:value.automatic.alternatives.map(option=>({
            id:option.id,title:this.optionTitle(option),summary:this.autoSummary(option),
            orders:option.comparison.rows.map(row=>this.handoffOrder(row,option)),
            moves:option.comparison.plan.transfers.map(move=>`${this.autoSource(move.source_ref)} · ${this.autoName(move.donor_ref)} → ${this.autoName(move.receiver_ref)} · ${this.number(move.quantity)} ${value.report.unit}`),
        }))});
    }
    async copyOption(option,mode='summary') {
        if(this.copyBusy)return;
        this.copyBusy=true;
        try {
        await this.refreshReviews();
        const text=mode==='full' ? this.handoffText(option) : this.handoffSummary(option);
        this.patch({handoffText:text,handoffMode:mode,handoffOption:option.id,copyStatus:this.copyMessage(mode,false),copyManual:true});
        try {
            if(!navigator.clipboard?.writeText)return;
            await navigator.clipboard.writeText(text);
            this.patch({copyStatus:this.copyMessage(mode,true),copyManual:false});
        }catch(_){/* The readonly text stays available when clipboard access is denied. */}
        }finally{this.copyBusy=false;}
    }
    autoRows(option) { return option.comparison.rows.map(r=>({...r,impact:option.comparison.impacts.find(i=>i.ref===r.ref)})); }
    autoModule(option) { return this.state.automatic.ai_recommendation?.modules?.find(m=>m.candidate_id===option.id); }
    get autoLateBefore() { return this.state.automatic?.report.rows.filter(r=>r.delayed_shortage>0).length || 0; }
    phrase(key, values) { return this.t(key).replace(/\{(\w+)\}/g, (_,name)=>values[name]); }
    autoSummary(option) {
        const c=option.comparison, before=c.material_wait_before_seconds, after=c.material_wait_after_seconds;
        const tone=this.metricTone(before,after);
        const wait=this.phrase({better:"waitLess",worse:"waitMore",neutral:"waitSame",unknown:"waitUnknown"}[tone],{
            before:this.hours(before),after:this.hours(after),delta:this.hours(Math.abs(Number(after)-Number(before))),
        });
        const late=this.phrase({better:"lateLess",worse:"lateMore",neutral:"lateSame"}[this.metricTone(this.autoLateBefore,option.metrics.late_orders)],{
            before:this.number(this.autoLateBefore),after:this.number(option.metrics.late_orders),
        });
        const residual=this.valueTone(c.unfilled)==="unknown" ? this.t("residualUnknown") : Number(c.unfilled)>0
            ? this.phrase("residualPositive",{quantity:this.number(c.unfilled),unit:this.state.automatic.report.unit}) : this.t("residualZero");
        return [wait,late,residual].join(" ");
    }
    async recommend(withAI=true) {
        if(this.state.busy || this.state.aiBusy)return;
        this.patch({busy:true,autoError:"",handoffText:"",handoffOption:"",copyStatus:""});
        try {
            const value=await this.orm.call("purchase.order","mdic_reallocation_recommend",[[this.props.orderId],
                this.props.lineId,this.props.arrival,withAI !== false && !!this.props.configured && !this.noAdjustmentNeeded,this.props.timezone,requestId()]);
            if(!value.automatic || !Array.isArray(value.automatic.alternatives))throw new Error("invalid options");
            this.patch({automatic:value});
            this.notifyRecommendation();
            await this.refreshReviews();
        }catch(_){this.patch({autoError:this.t("autoFailed")});}
        finally{this.patch({busy:false});}
    }
    async rpc(receiver, transfers, expected) {
        return this.orm.call("purchase.order", "mdic_reallocation", [[this.props.orderId], this.props.lineId,
            this.props.arrival, receiver, transfers, expected]);
    }
    async prepare() {
        if (this.state.busy || this.state.aiBusy) return;
        this.patch({busy:true,error:"",aiError:""});
        try {
            const prepared = await this.rpc(null, null, null);
            this.patch({prepared, receiver:"", candidates:[], selected:"", quantity:"", plan:[], comparison:null, ai:null});
        } catch (_) { this.patch({error:this.t("failed")}); }
        finally { this.patch({busy:false}); }
    }
    async onReceiver(event) {
        if (this.state.busy || this.state.aiBusy) return;
        const receiver = event.target.value;
        this.patch({receiver,selected:"",quantity:"",candidates:[],error:""});
        if (!receiver) return;
        this.patch({busy:true});
        try {
            const value = await this.rpc(receiver, null, this.state.prepared.facts_key);
            this.patch({candidates:value.candidates});
        } catch (_) { this.patch({error:this.t("stale")}); }
        finally { this.patch({busy:false}); }
    }
    onCandidate(event) { const selected=event.target.value; this.patch({selected,quantity:this.state.candidates[Number(selected)]?.quantity || ""}); }
    onQuantity(event) { this.patch({quantity:event.target.value}); }
    add() {
        const candidate = this.state.selected === "" ? null : this.state.candidates[Number(this.state.selected)];
        const quantity = this.state.quantity.trim().replace(",", ".");
        if (!candidate || !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(quantity) || Number(quantity) <= 0) { this.patch({error:this.t("invalid")}); return; }
        const transfer = {source_ref:candidate.source_ref,donor_ref:candidate.donor_ref,receiver_ref:candidate.receiver_ref,quantity};
        if (this.state.plan.some(p => p.source_ref === transfer.source_ref && p.donor_ref === transfer.donor_ref && p.receiver_ref === transfer.receiver_ref)) {
            this.patch({error:this.t("duplicate")}); return;
        }
        this.patch({plan:[...this.state.plan,transfer],comparison:null,ai:null,aiError:"",error:""});
    }
    remove(index) { this.patch({plan:this.state.plan.filter((_,i)=>i!==index),comparison:null,ai:null,aiError:"",error:""}); }
    async compare() {
        if (this.state.busy || this.state.aiBusy || !this.state.plan.length) return;
        this.patch({busy:true,error:"",comparison:null,ai:null,aiError:""});
        try {
            const value=await this.rpc(null,clone(this.state.plan),this.state.prepared.facts_key);
            this.patch({comparison:value.comparison});
        } catch (_) { this.patch({error:this.t("failed")}); }
        finally { this.patch({busy:false}); }
    }
    async explain() {
        if (this.state.busy || this.state.aiBusy || this.state.error || !this.state.comparison || !this.props.configured || !this.state.prepared.ai_interpretation_enabled) return;
        this.patch({aiBusy:true,ai:null,aiError:""});
        try {
            const value=await this.orm.call("purchase.order","mdic_reallocation_ai",[[this.props.orderId],this.props.lineId,
                this.props.arrival,clone(this.state.plan),this.state.prepared.facts_key,this.props.timezone,requestId()]);
            if (value.status !== "verified" || value.facts_key !== this.state.prepared.facts_key) throw new Error("unverified");
            this.patch({ai:value});
        } catch (_) { this.patch({aiError:this.t("aiFailed")}); }
        finally { this.patch({aiBusy:false}); }
    }
}
