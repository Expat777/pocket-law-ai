"""Реестр актов: код акта -> параметры источника (ИПС «Законодательство России»).

nd — идентификатор документа в ИПС, см. SOURCE.md, раздел «Как добавить новый акт».
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActInfo:
    code: str        # ключ CLI: --act tk_rf
    act: str         # каноническое имя для payload/цитат: "ТК РФ"
    nd: str          # id документа в ИПС
    min_articles: int  # защита парсера: меньше — значит источник сломался

    @property
    def url(self) -> str:
        """Устойчивая ссылка на акт в ИПС (на документ целиком; анкоров на статью
        у ИПС нет — см. SOURCE.md). Реальная рабочая ссылка, а не фабрикация под статью."""
        return f"http://pravo.gov.ru/proxy/ips/?docbody=&nd={self.nd}"


ACTS: dict[str, ActInfo] = {
    "tk_rf": ActInfo(code="tk_rf", act="ТК РФ", nd="102074279", min_articles=400),
    # Семейный кодекс РФ (29.12.1995 № 223-ФЗ): nd сверен, парсится штатно (177 ст. → 183 чанка),
    # межзаконная интерференция с ТК измерена и ничтожна (MRR −0.005). Готов к боевому прогону.
    "sk_rf": ActInfo(code="sk_rf", act="СК РФ", nd="102038925", min_articles=100),
    # Закон РФ 07.02.1992 № 2300-1 «О защите прав потребителей» (nd сверен, ФЗ не кодекс).
    # Парсер доработан под ФЗ (голые стабы утративших силу статей → repealed): 55 ст. → 75 чанков.
    "zpp_rf": ActInfo(code="zpp_rf", act="ЗоЗПП", nd="102014512", min_articles=40),
    # --- Tier-2 (2026-07-08): nd сверены фетчем, парсятся штатно; строки act = контракт Роли 2
    #     (agent/config.py::BRANCH_TO_ACTS). ГК и НК многочастные — один act на все части
    #     (номера статей между частями не пересекаются, id namespace по act не конфликтует).
    "uk_rf":    ActInfo(code="uk_rf",    act="УК РФ",   nd="102041891", min_articles=400),  # 535 ст.
    "gk_rf_1":  ActInfo(code="gk_rf_1",  act="ГК РФ",   nd="102033239", min_articles=400),  # ч.1, 594 ст.
    "gk_rf_2":  ActInfo(code="gk_rf_2",  act="ГК РФ",   nd="102039276", min_articles=500),  # ч.2, 685 ст.
    "gk_rf_3":  ActInfo(code="gk_rf_3",  act="ГК РФ",   nd="102073578", min_articles=80),   # ч.3, 123 ст. (наследство)
    "gk_rf_4":  ActInfo(code="gk_rf_4",  act="ГК РФ",   nd="102110716", min_articles=250),  # ч.4, 334 ст.
    "koap_rf":  ActInfo(code="koap_rf",  act="КоАП РФ", nd="102074277", min_articles=800),  # 1142 ст.
    "zhk_rf":   ActInfo(code="zhk_rf",   act="ЖК РФ",   nd="102090645", min_articles=150),  # 243 ст.
    "nk_rf_1":  ActInfo(code="nk_rf_1",  act="НК РФ",   nd="102054722", min_articles=200),  # ч.1, 275 ст.
    "gpk_rf":   ActInfo(code="gpk_rf",   act="ГПК РФ",  nd="102078828", min_articles=350),  # 499 ст.
    "upk_rf":   ActInfo(code="upk_rf",   act="УПК РФ",  nd="102073942", min_articles=400),  # 560 ст.
    "nk_rf_2":  ActInfo(code="nk_rf_2",  act="НК РФ",  nd="102067058", min_articles=400),  # ч.2, 540 ст. (fulltext-фолбэк)
}
