"""Compile unchanged pinned LocalInsulin.kt with data stubs and compare Python.

No patient records, application modules or default model parameters are used.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--java", required=True)
parser.add_argument("--kotlin-lib", required=True)
args = parser.parse_args()
manifest = json.loads((root / "aaps/manifest.json").read_text())
for name, entry in manifest["files"].items():
    if hashlib.sha256((root / "aaps" / name).read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"Reference hash mismatch: {name}")
spec = importlib.util.spec_from_file_location("research_insulin", root / "research/insulin_component.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
base = 1_700_000_000_000
cases = []
for dia in (3.0, 5.0, 6.0, 8.0, 12.0):
    duration_ms = int(max(5.0, dia) * 3_600_000)
    for peak in (35, 55, 65, 75, 120):
        for amount in (-0.05, 0.0, 0.05, 1.0, 8.75):
            for elapsed_ms in sorted({0, 1, 30_000, 60_000, peak * 60_000,
                                      duration_ms // 2, duration_ms - 1, duration_ms, duration_ms + 1}):
                cases.append((amount, elapsed_ms, peak, dia))
wrapper = '''import app.aaps.plugins.aps.autotune.data.LocalInsulin
import app.aaps.core.data.model.BS
fun main() {
while(true) {
val line = readlnOrNull() ?: break
val p = line.split(",")
val insulin = LocalInsulin("synthetic", p[2].toInt(), p[3].toDouble())
val result = insulin.iobCalcForTreatment(BS(p[0].toDouble(), 1700000000000L), 1700000000000L + p[1].toLong())
println("${result.iobContrib},${result.activityContrib}")
}
}
'''
with tempfile.TemporaryDirectory(prefix="aaps-insulin-parity-") as temp:
    path = Path(temp)
    (path / "Runner.kt").write_text(wrapper)
    (path / "BS.kt").write_text("package app.aaps.core.data.model\ndata class BS(val amount:Double,val timestamp:Long)\n")
    (path / "Iob.kt").write_text("package app.aaps.core.data.iob\nclass Iob { var iobContrib:Double=0.0; var activityContrib:Double=0.0 }\n")
    env = dict(os.environ, JAVA_HOME=str(Path(args.java).resolve().parent.parent))
    subprocess.run([args.java, "-cp", str(Path(args.kotlin_lib) / "*"),
                    "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", str(path / "Runner.kt"),
                    str(path / "BS.kt"), str(path / "Iob.kt"), str(root / "aaps/LocalInsulin.kt"),
                    "-include-runtime", "-d", str(path / "runner.jar")], env=env, check=True)
    result = subprocess.run([args.java, "-jar", str(path / "runner.jar")],
                            input="\n".join(",".join(map(str, case)) for case in cases) + "\n",
                            text=True, capture_output=True, check=True)
    outputs = result.stdout.splitlines()
    if len(outputs) != len(cases):
        raise AssertionError("Missing Kotlin results")
    maximum = 0.0
    for case, line in zip(cases, outputs):
        expected = list(map(float, line.split(",")))
        amount, elapsed_ms, peak, dia = case
        actual = module.insulin_contribution(amount, elapsed_ms / 1000.0 / 60.0, peak, dia)
        for x, y in zip(expected, actual):
            if not math.isfinite(x) or not math.isfinite(y) or abs(x - y) > 1e-10:
                raise AssertionError((case, expected, actual))
            maximum = max(maximum, abs(x - y))
    # Separate domain checks: the production caller must never send future doses.
    for case in [(1, -1, 75, 6), (1, 0, 180, 6), (1, 0, 0, 6), (1, 0, 75, None), (1, 0, 75, 0)]:
        try:
            module.insulin_contribution(*case)
        except ValueError:
            pass
        else:
            raise AssertionError(("unsupported input accepted", case))
    evidence = {"reference_commit": manifest["commit"], "component": "unchanged LocalInsulin.kt",
                "cases": len(cases), "compared_values": 2 * len(cases),
                "maximum_absolute_difference": maximum,
                "scope": "Single explicit synthetic contribution only; not delivery reconstruction, historical configuration, total IOB or clinical validation.",
                "python_sha256": hashlib.sha256((root / "research/insulin_component.py").read_bytes()).hexdigest(),
                "kotlin_sha256": manifest["files"]["LocalInsulin.kt"]["sha256"]}
    (root / "insulin-parity-result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
