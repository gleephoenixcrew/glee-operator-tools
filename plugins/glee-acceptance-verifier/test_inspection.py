"""Offline regressions for the inspection helper's observed failure modes."""
from pathlib import Path
from contextlib import redirect_stderr
from unittest.mock import patch
import importlib.util
import io,json,unittest

ROOT=Path(__file__).resolve().parent
SKILL=ROOT/'skills/glee-patch-acceptance'
spec=importlib.util.spec_from_file_location('inspection',SKILL/'scripts/inspect_service.py')
inspection=importlib.util.module_from_spec(spec);spec.loader.exec_module(inspection)

class Response:
    def __init__(self,body): self.body=json.dumps(body).encode()
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,*args): return self.body

class InspectionTests(unittest.TestCase):
    def test_wrong_type_and_incomplete_contract_fail_as_structured_errors(self):
        for body in [None,[],{'id':'patch_verification'}]:
            with self.subTest(body=body):
                error=io.StringIO()
                with patch.object(inspection,'build_opener') as factory,redirect_stderr(error):
                    factory.return_value.open.return_value=Response(body)
                    self.assertEqual(inspection.main(['contract']),1)
                self.assertFalse(json.loads(error.getvalue())['paid_request_sent'])

    def test_observed_contract_is_usable(self):
        body=json.loads((SKILL/'references/contract-observed.json').read_text())['contract']
        inspection.validate_document(body,'contract',None)

    def test_preview_flags_without_an_evaluated_result_are_rejected(self):
        body={'schema':'glee.patch_preview.v1','case':'pass','payment_execution':False,'signed_receipt':False}
        with self.assertRaises(ValueError): inspection.validate_document(body,'preview','pass')

    def test_only_fixed_get_inputs_are_sent(self):
        body=json.loads((SKILL/'references/contract-observed.json').read_text())['contract']
        with patch.object(inspection,'build_opener') as factory:
            factory.return_value.open.return_value=Response(body)
            inspection.fetch('contract',internal=True)
            request=factory.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(),'GET');self.assertIsNone(request.data)
        self.assertIn('ref=glee_int_cursor_20261018',request.full_url)

if __name__=='__main__': unittest.main()
