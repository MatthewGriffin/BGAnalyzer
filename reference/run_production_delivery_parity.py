"""Synthetic executable checks of production net-basal conversion and total IOB.

Pinned Kotlin kernels are compiled without edits. Android persistence/profile
services are explicit stubs; raw-event ambiguity is tested separately in pytest.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from bganalyzer.autotune.net_basal import segment_contributions
from bganalyzer.autotune.categorize import AutotuneIob, AutotuneIobData, Treatment
from bganalyzer.autotune.models import LocalInsulin, Round

parser = argparse.ArgumentParser()
parser.add_argument('--java', required=True)
parser.add_argument('--kotlin-lib', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
manifest = json.loads((root/'aaps/manifest.json').read_text())
for name, entry in manifest['files'].items():
    assert hashlib.sha256((root/'aaps'/name).read_bytes()).hexdigest() == entry['sha256'], name
source = (root/'aaps/AutotuneIob.kt').read_text()
section = source[source.index('    private fun convertToBoluses(tbr: TB'):source.index('    fun BS.toJson')]
extension = (root/'aaps/TemporaryBasalExtension.kt').read_text()
a = extension.index('val TB.durationInMinutes')
extension = extension[a:extension.index('\n', extension.index('get() =', a))]
wrapper = '''import kotlin.math.ceil
import app.aaps.core.interfaces.utils.Round
import app.aaps.core.data.time.T
import app.aaps.core.data.model.BS
import app.aaps.core.data.model.IDs
import app.aaps.plugins.aps.autotune.data.LocalInsulin
data class TB(val timestamp:Long,val duration:Long,val rate:Double,val isAbsolute:Boolean,val ids:IDs=IDs())
class Profile(val rate:Double) {fun getBasal(timestamp:Long):Double=rate}
''' + extension + '\n' + section + '''
fun main() {
while(true) {
val line=readlnOrNull() ?: break
val p=line.split(",")
val ts=p[0].toLong()
val parts=convertToBoluses(TB(ts,p[1].toLong(),p[2].toDouble(),p[3].toBoolean()),Profile(p[4].toDouble()),Profile(p[5].toDouble()))
val insulin=LocalInsulin("test",75,6.0)
val values=listOf(ts,ts+1800000,ts+7200000,ts+21600000).map { now ->
    var iob=0.0; var activity=0.0
    for(b in (parts + listOf(BS(timestamp=ts-600000,amount=1.2),BS(timestamp=ts+300000,amount=0.1),
                         BS(timestamp=ts-100000000,amount=8.0),BS(timestamp=ts,amount=99.0,isValid=false),
                         BS(timestamp=ts,amount=99.0,type=BS.Type.PRIMING))).sortedByDescending{it.timestamp}) {
        if (!b.isValid || b.type==BS.Type.PRIMING || b.timestamp>now || b.timestamp<now-insulin.duration) continue
        val v=insulin.iobCalcForTreatment(b,now); iob+=v.iobContrib; activity+=v.activityContrib
    }
    "${Round.roundTo(iob,0.001)},${Round.roundTo(activity,0.001)}"
}
println(parts.joinToString(";"){"${it.timestamp},${it.amount}"} + "|" + values.joinToString(";"))
}}
'''
cases = [(1700000000000, duration, rate, absolute, basal, tuned)
         for duration in (0,59999,60000,299999,300000,301000,659999,1800001,3600000)
         for absolute,rates in ((True,(0.,0.0005,0.9995,1.5,3.)),(False,(0.,50.,100.,150.,200.)))
         for rate in rates for basal,tuned in ((0.,0.),(1.,1.),(0.,1.),(1.,1.2))]
with tempfile.TemporaryDirectory(prefix='bg-production-delivery-') as temporary:
    path=Path(temporary)
    (path/'Runner.kt').write_text(wrapper)
    (path/'BS.kt').write_text('''package app.aaps.core.data.model
class IDs {var nightscoutId:String?="synthetic"}
data class BS(val ids:IDs=IDs(),val timestamp:Long,val amount:Double,val type:Type=Type.NORMAL,val isValid:Boolean=true) {enum class Type {NORMAL,PRIMING}}
''')
    (path/'Iob.kt').write_text('package app.aaps.core.data.iob\nclass Iob {var iobContrib:Double=0.0; var activityContrib:Double=0.0}\n')
    env=dict(os.environ,JAVA_HOME=str(Path(args.java).resolve().parent.parent))
    subprocess.run([args.java,'-cp',str(Path(args.kotlin_lib)/'*'),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                    str(path/'Runner.kt'),str(path/'BS.kt'),str(path/'Iob.kt'),str(root/'aaps/LocalInsulin.kt'),
                    str(root/'aaps/Round.kt'),str(root/'aaps/T.kt'),'-include-runtime','-d',str(path/'runner.jar')],
                   env=env,check=True)
    inputs=['%s,%s,%s,%s,%s,%s' % (ts,duration,rate,str(absolute).lower(),basal,tuned)
            for ts,duration,rate,absolute,basal,tuned in cases]
    lines=subprocess.run([args.java,'-jar',str(path/'runner.jar')],input='\n'.join(inputs)+'\n',
                         text=True,capture_output=True,check=True).stdout.splitlines()
    assert len(lines)==len(cases)
    maximum=0.0; count=0; totals=0
    for case,line in zip(cases,lines):
        parts,expected_totals=line.split('|')
        expected=[(int(p.split(',')[0]),float(p.split(',')[1])) for p in parts.split(';')] if parts else []
        actual=segment_contributions(*case)
        assert len(actual)==len(expected), case
        for (at,av),(et,ev) in zip(actual,expected):
            assert at==et and abs(av-ev)<=1e-10,(case,actual,expected)
            maximum=max(maximum,abs(av-ev));count+=1
        ts=case[0]
        boluses=[Treatment(t,a,type='NET_BASAL') for t,a in actual]+[
            Treatment(ts-600000,1.2),Treatment(ts+300000,.1,type='smb'),
            Treatment(ts-100000000,8),Treatment(ts,99,is_valid=False),Treatment(ts,99,type='PRIMING')]
        calculator=AutotuneIob(AutotuneIobData(boluses=boluses))
        for stamp,values in zip((ts,ts+1800000,ts+7200000,ts+21600000),expected_totals.split(';')):
            expected_values=list(map(float,values.split(',')))
            result=calculator.getIOB(stamp,LocalInsulin(None,75,6))
            for a,b in zip((result.iob,result.activity),expected_values):
                assert math.isfinite(a) and abs(a-b)<=1e-10,(case,stamp,a,b)
                maximum=max(maximum,abs(a-b));totals+=1
    files=['src/bganalyzer/autotune/net_basal.py','src/bganalyzer/autotune/categorize.py',
           'src/bganalyzer/autotune/models.py','src/bganalyzer/autotune/orchestration.py',
           'src/bganalyzer/timeline/insulin.py','src/bganalyzer/timeline/basal_delivery.py']
    evidence=dict(reference_commit=manifest['commit'],cases=len(cases),contributions_compared=count,
                  iob_activity_values_compared=totals,maximum_absolute_difference=maximum,
                  scope='Production resolved-segment conversion and summed IOB/activity; not Android persistence, raw-event semantics, full prep/tuning or physical pump delivery.',
                  source_hashes={name:hashlib.sha256((root.parent/name).read_bytes()).hexdigest() for name in files})
    (root/'production-delivery-parity-result.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))
