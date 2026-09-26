"""Generated macro inventory. No claims are inferred from a successful LaTeX build."""
from __future__ import annotations
import re
from contracts import *
from metrics import summary

PREFIX={"nslkdd":"Nsl","unsw":"Unsw","cicids2017":"Cic","iot23":"Iot"}
METRIC_NAME={"overall_acc":"Oa","macro_f1":"MacroFone"}
PAPER_METRICS={**METRIC_NAME,"mcc":"Mcc","balanced_acc":"BalancedAcc",
               "macro_precision":"MacroPrecision","macro_recall":"MacroRecall",
               "weighted_f1":"WeightedFone","roc_auc_macro":"RocAucMacro"}


def _latex_number(value, *, signed=False):
    value=finite(value,"formatted number")
    if value == 0:
        return "0"
    text=format(value,"+.8g" if signed else ".8g")
    if "e" not in text.lower():
        return text
    mantissa,exponent=re.split("[eE]",text)
    return mantissa+r"\mathbin{\times}10^{"+str(int(exponent))+"}"


def fmt_p(p):
    if p is None: return r"\text{undefined}"
    p=finite(p,"p value");require(0<=p<=1,"Invalid p")
    return _latex_number(p)


def fmt_effect(value):
    return _latex_number(value,signed=True)


def _metric_text(metric,values):
    s=summary(values);digits=3 if metric in ("mcc","roc_auc_macro") else 2
    mean=f"{s['mean']:.{digits}f}"
    return mean if s['std'] is None else mean+f"\\mathbin{{\\pm}}{s['std']:.{digits}f}"


def expected_macros(plan,results,difference,equivalence,tree_report):
    values={"vFiveSeeds":str(len(plan["seeds"])),"vFiveAlpha":str(plan["alpha"]),
            "vFiveMargin":str(plan["equivalence_margin_pp"])}
    for (dataset,arm),r in results.items():
        prefix="vFive"+PREFIX[dataset]+arm.capitalize()
        for metric,name in PAPER_METRICS.items():
            text=_metric_text(metric,[row[metric] for row in r["per_seed"]])
            require("pm" in text,"Neural paper macros need at least two valid seeds")
            values[prefix+name]=text
        for part,name in (("fit","FitCount"),("validation","ValidationCount"),("test","TestCount")):
            values[prefix+name]=str(r["counts"][part])
    for key,w in difference["comparisons"].items():
        dataset,comparison,metric=key.split(":")
        arm=comparison.removeprefix("relu_vs_")
        prefix="vFive"+PREFIX[dataset]+"ReluVs"+arm.capitalize()+METRIC_NAME[metric]
        values[prefix+"RawP"]=fmt_p(w["p_raw"])
        values[prefix+"HolmP"]=fmt_p(w["p_adj"])
        values[prefix+"MeanDifference"]=fmt_effect(w["mean_diff"])
        values[prefix+"PseudomedianDifference"]=fmt_effect(
            w["hodges_lehmann_pseudomedian_diff"]
        )
        values[prefix+"DifferenceSupported"]="yes" if w["reject"] else "no"
    for key,q in equivalence["pairs"].items():
        dataset,metric=key.split(":")
        prefix="vFive"+PREFIX[dataset]+"Equivalence"+METRIC_NAME[metric]
        values[prefix+"HolmP"]=fmt_p(q["holm"]["p_adj"])
        values[prefix+"Supported"]="yes" if q["equivalent_familywise"] else "no"
        values[prefix+"SignedRankHolmP"]=fmt_p(
            q["signed_rank_robustness_holm"]["p_adj"]
        )
        values[prefix+"SignedRankSupported"]=(
            "yes" if q["equivalent_familywise_signed_rank_robustness"] else "no"
        )
        values[prefix+"Discordant"]=(
            "yes" if q["primary_robustness_discordant"] else "no"
        )
    for dataset in ("nslkdd","unsw"):
        for kind,model_name in (("random_forest","RandomForest"),("xgboost","Xgboost")):
            result=tree_report["results"][dataset][kind]
            prefix="vFive"+PREFIX[dataset]+model_name
            values[prefix+"Seeds"]=str(len(result["per_seed"]))
            values[prefix+"UniqueModels"]=str(result["n_unique_model_digests"])
            for metric,name in PAPER_METRICS.items():
                values[prefix+name]=_metric_text(metric,[row[metric] for row in result["per_seed"]])
    return values


def macro_text(values):
    lines=["% Generated version-5 numerical view. Do not hand-edit.",
           "% Percent metrics are already percent; do not multiply recalls by 100 again.",
           "% This file does not validate SNN, deployment, latency, energy, or natural-language claims."]
    for name,value in sorted(values.items()):
        require(re.fullmatch(r"[A-Za-z]+",name) is not None,"LaTeX macro name must contain letters only")
        lines.append("\\newcommand{\\"+name+"}{\\ensuremath{"+value+"}}")
    return '\n'.join(lines)+'\n'


def strip_comments(text):
    output=[]
    for line in text.splitlines():
        cut=len(line)
        for i,c in enumerate(line):
            if c=="%":
                k=i-1
                while k>=0 and line[k]=="\\":k-=1
                if (i-1-k)%2==0:cut=i;break
        output.append(line[:cut])
    return '\n'.join(output)


def tex_sources(main: Path):
    root=main.parent.resolve();seen=set();active=set();output={}
    def visit(path):
        path=path.resolve()
        require(path.is_relative_to(root),"TeX input escapes the declared paper directory")
        require(path not in active,"Cyclic TeX input")
        if path in seen:return
        require(path.is_file(),f"Missing TeX input: {path}")
        active.add(path);text=strip_comments(path.read_text(encoding="utf-8"));output[path.relative_to(root).as_posix()]=text
        directives = list(re.finditer(r"\\(?:input|include)\b", text))
        inputs = list(re.finditer(r"\\(?:input|include)\s*\{([^{}]+)\}", text))
        require([m.start() for m in directives] == [m.start() for m in inputs],
                "Shorthand/dynamic TeX input is outside the scanner contract; use literal braced inputs")
        require(not re.search(r"\\(?:includeonly|InputIfFileExists|inputminted|verbatiminput)\b", text),
                "Conditional/alternate input commands need explicit source expansion")
        for match in inputs:
            raw = match.group(1)
            require("\\" not in raw and "#" not in raw,"Dynamic TeX inputs require explicit source expansion")
            target=root/raw
            if not target.suffix:target=target.with_suffix(".tex")
            visit(target)
        active.remove(path);seen.add(path)
    visit(main)
    return output


def prose_findings(main):
    files=tex_sources(main)
    require("result_macros_v5.tex" in files,"main.tex does not input the version-5 macro file")
    issues=[]
    patterns=[r"\bp\s*(?:_\{?adj\}?\s*)?\{?[=<>]\}?\s*~?\s*0\.\d+",
              r"\d+\.\d+\s*(?:\\pm|\$\\pm\$|±)\s*\d+\.\d+",
              r"FP32\s+ReLU\s*=\s*T",
              r"(?i)(?:QCFS|ReLU).{0,25}(?:T\s*[={} ]+1).{0,25}(?:SNN|LIF)"]
    for name,text in files.items():
        if name=="result_macros_v5.tex":continue
        if re.search(r"\\(?:newcommand|renewcommand|providecommand|def|let).*?vFive", text):
            issues.append(f"{name}: redefinition of a generated vFive macro")
        if "result_macros.tex" in text or "IfFileExists" in text:
            issues.append(f"{name}: old/fallback result macro path; remove or explicitly reconcile it")
        for number,line in enumerate(text.splitlines(),1):
            for pattern in patterns:
                if re.search(pattern,line):issues.append(f"{name}:{number}: review literal result/unsupported identity: {line.strip()[:160]}")
    return issues
