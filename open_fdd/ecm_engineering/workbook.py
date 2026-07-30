from __future__ import annotations
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any
import json
import shutil
import zipfile
import xml.etree.ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", MAIN)
ET.register_namespace("r", REL)

def _resource(name: str):
    return files("open_fdd.ecm_engineering.data").joinpath(name)

def create_workbook(output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with as_file(_resource("Open_FDD_ECM_Engineering_Toolkit.xlsx")) as src:
        shutil.copyfile(src, output)
    return output

class OpenFDDECMWorkbook:
    def __init__(self, workbook_path: str | Path):
        self.path = Path(workbook_path)
        with as_file(_resource("open_fdd_model.json")) as src:
            self.model = json.loads(Path(src).read_text(encoding="utf-8"))

    @classmethod
    def create(cls, output_path: str | Path) -> "OpenFDDECMWorkbook":
        return cls(create_workbook(output_path))

    def list_modules(self) -> list[str]:
        return list(self.model["modules"])

    def module_api_keys(self, module: str) -> dict[str, str]:
        return dict(self.model["modules"][module]["cells"])

    def _api_ref(self, api_key: str) -> tuple[str, str]:
        if api_key in self.model.get("global_inputs", {}):
            return tuple(self.model["global_inputs"][api_key].split("!", 1))  # type: ignore[return-value]
        for module in self.model["modules"].values():
            if api_key in module["cells"]:
                return module["sheet"], module["cells"][api_key]
        raise KeyError(f"unknown API key: {api_key}")

    def _sheet_paths(self, zin: zipfile.ZipFile) -> dict[str, str]:
        workbook = ET.fromstring(zin.read("xl/workbook.xml"))
        rels = ET.fromstring(zin.read("xl/_rels/workbook.xml.rels"))
        targets = {
            node.attrib["Id"]: node.attrib["Target"]
            for node in rels.findall(f"{{{PKG_REL}}}Relationship")
        }
        result = {}
        sheets = workbook.find(f"{{{MAIN}}}sheets")
        if sheets is None:
            return result
        for sheet in sheets:
            rid = sheet.attrib[f"{{{REL}}}id"]
            target = targets[rid].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            result[sheet.attrib["name"]] = target
        return result

    @staticmethod
    def _set_value(cell: ET.Element, value: Any) -> None:
        if cell.find(f"{{{MAIN}}}f") is not None:
            raise ValueError("cannot overwrite an Excel formula cell")
        for child in list(cell):
            if child.tag in {f"{{{MAIN}}}v", f"{{{MAIN}}}is"}:
                cell.remove(child)

        if isinstance(value, bool):
            cell.set("t", "b")
            node = ET.SubElement(cell, f"{{{MAIN}}}v")
            node.text = "1" if value else "0"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            cell.attrib.pop("t", None)
            node = ET.SubElement(cell, f"{{{MAIN}}}v")
            node.text = repr(value)
        else:
            cell.set("t", "inlineStr")
            is_node = ET.SubElement(cell, f"{{{MAIN}}}is")
            text = ET.SubElement(is_node, f"{{{MAIN}}}t")
            text.text = str(value)

    def set(self, api_key: str, value: Any) -> None:
        self.set_many({api_key: value})

    def set_many(self, values: dict[str, Any]) -> None:
        refs = {key: self._api_ref(key) for key in values}
        tmp = self.path.with_suffix(".xlsx.tmp")

        with zipfile.ZipFile(self.path, "r") as zin:
            paths = self._sheet_paths(zin)
            updates: dict[str, list[tuple[str, str, Any]]] = {}
            for key, (sheet, cell) in refs.items():
                updates.setdefault(paths[sheet], []).append((key, cell, values[key]))

            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    payload = zin.read(item.filename)
                    if item.filename in updates:
                        root = ET.fromstring(payload)
                        for key, address, value in updates[item.filename]:
                            cell = root.find(f".//{{{MAIN}}}c[@r='{address}']")
                            if cell is None:
                                raise KeyError(f"{key}: cell {address} was not found")
                            self._set_value(cell, value)
                        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                    elif item.filename == "xl/workbook.xml":
                        root = ET.fromstring(payload)
                        calc_pr = root.find(f"{{{MAIN}}}calcPr")
                        if calc_pr is None:
                            calc_pr = ET.SubElement(root, f"{{{MAIN}}}calcPr")
                        calc_pr.set("fullCalcOnLoad", "1")
                        calc_pr.set("forceFullCalc", "1")
                        calc_pr.set("calcMode", "auto")
                        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                    zout.writestr(item, payload)

        tmp.replace(self.path)

    def save_as(self, output_path: str | Path) -> Path:
        """Copy workbook to ``output_path``.

        Idempotent when ``output_path`` resolves to the current path (inputs are
        already persisted by ``set_many`` / ``create``). Otherwise copies and
        retargets ``self.path``.
        """
        output = Path(output_path).resolve()
        current = Path(self.path).resolve()
        if output == current:
            return current
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(current, output)
        self.path = output
        return output
