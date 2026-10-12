import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import task_generate_v2 as gen
import task_admissibility as admission

class LargeMechanismTests(unittest.TestCase):
    def test_large_commands_run_all_cases(self):
        self.assertIn('--no-fail-fast',gen.layout('rust','example','large')['argv'])
        self.assertEqual(gen.layout('rust','example','small')['argv'],['cargo','test'])
        self.assertIn('--test',gen.layout('typescript','example','large')['argv'])
        self.assertIn('node:test',gen.size_instruction('typescript','large'))
        self.assertIn('full long collections',gen.size_instruction('rust','large'))
        self.assertNotIn('3-5',gen.TESTS_SYSTEM)
    def test_node_collects_both_failures_and_full_long_payloads(self):
        body="""import test from 'node:test';
import assert from 'node:assert/strict';
for (const name of ['case_one','case_two']) test(name, () => {
  assert.deepStrictEqual(Array.from({length:40},(_,i)=>'actual-'+i),
                        Array.from({length:40},(_,i)=>'expected-'+i));
});
"""
        ok, output=gen.run_suite({'check.mjs':body},gen.layout('typescript','example','large')['argv'])
        self.assertIs(ok,False)
        for text in ('case_one','case_two','actual-39','expected-39'):
            self.assertIn(text,output)
        body=body.replace("'expected-'","'actual-'")
        self.assertIs(gen.run_suite({'check.mjs':body},gen.layout('typescript','example','large')['argv'])[0],True)
    def test_A8_counts_utf8_characters_from_both_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate=Path(tmp); (candidate/'fixture').mkdir()
            (candidate/'fixture/emit.py').write_text(
                "import sys; b=bytes.fromhex('e28094')*40; sys.stdout.buffer.write(b); sys.stderr.buffer.write(b); sys.exit(1)",encoding='utf-8')
            pred={'type':'command_exit_0','argv':[sys.executable,'emit.py']}
            self.assertEqual(admission.pristine_observation_tokens(candidate,pred),20)
if __name__=='__main__': unittest.main()
