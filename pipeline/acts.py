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
    # "gk_rf_1": ActInfo(...)  # добавлять по одной строке, nd искать по SOURCE.md
}
