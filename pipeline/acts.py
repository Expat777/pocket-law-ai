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


ACTS: dict[str, ActInfo] = {
    "tk_rf": ActInfo(code="tk_rf", act="ТК РФ", nd="102074279", min_articles=400),
    # "gk_rf_1": ActInfo(...)  # добавлять по одной строке, nd искать по SOURCE.md
}
