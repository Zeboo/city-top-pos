import json, unittest, urllib.request, urllib.error, http.cookiejar
BASE='http://127.0.0.1:8765'
class WebWorkflows(unittest.TestCase):
 def setUp(self):
  self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def call(self,path,data=None,method=None):
  req=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method)
  with self.client.open(req) as r:
   body=r.read(); return json.loads(body) if 'application/json' in r.headers.get('Content-Type','') else body
 def login(self,role='owner'):
  self.call('/api/login',{'username':role,'password':role+'123','role':role})
 def test_full_workflow(self):
  self.login(); menu=self.call('/api/menu'); v=next(v for c in menu['categories'] for p in c['products'] for v in p['variants'])
  o=self.call('/api/orders',{'lines':[{'variant_id':v['id'],'quantity':2}],'discount':10,'tax_rate':5,'order_type':'delivery','customer_name':'Test Guest','customer_phone':'123','customer_address':'Test address'})
  self.assertAlmostEqual(o['total'],round(max(0,v['price']*2-10)*1.05,2))
  self.assertEqual(o['items'][0]['quantity'],2);self.assertEqual(o['items'][0]['unit_price'],v['price']);self.assertEqual(o['items'][0]['total'],v['price']*2)
  self.call('/api/orders/'+str(o['id'])+'/status',{'status':'pending'})
  self.call('/api/cashback/'+str(o['id'])+'/approve',{})
  found=next(x for x in self.call('/api/orders') if x['id']==o['id']);self.assertEqual(found['net_total'],0)
  with self.assertRaises(urllib.error.HTTPError) as err:self.call('/api/orders/'+str(o['id'])+'/status',{'status':'approved'})
  self.assertEqual(err.exception.code,409)
  self.call('/api/guests',{'name':'Workflow Guest','phone':'456'});self.assertTrue(self.call('/api/guests?search=Workflow'))
  payload={'category_id':menu['categories'][0]['id'],'name':'Workflow product','price':123,'description':'Test'}
  p=self.call('/api/management/products',payload);payload['price']=234
  self.call('/api/management/products/'+str(p['id']),payload,'PUT');self.assertEqual(next(x for x in self.call('/api/management/products') if x['id']==p['id'])['price'],234)
  self.call('/api/management/products/'+str(p['id']),method='DELETE')
  self.assertFalse(any(x['id']==p['id'] for x in self.call('/api/management/products')))
  self.call('/api/management/users',{'username':'test-user','password':'test-password','role':'cashier'})
  u=next(x for x in self.call('/api/management/users') if x['username']=='test-user');self.call('/api/management/users/'+str(u['id'])+'/toggle',{})
  self.assertIn('orders',self.call('/api/management/backup')['tables'])
  self.assertIn(b'Order,Date',self.call('/api/reports.csv?status=approved'))
 def test_permissions_validation_assets(self):
  with self.assertRaises(urllib.error.HTTPError) as err:self.call('/api/menu')
  self.assertEqual(err.exception.code,401);self.login('cashier')
  for path in ['/api/guests','/api/management/products','/api/management/users','/api/management/backup']:
   with self.assertRaises(urllib.error.HTTPError) as err:self.call(path)
   self.assertEqual(err.exception.code,403)
  with self.assertRaises(urllib.error.HTTPError) as err:self.call('/api/orders',{'lines':[{'variant_id':1,'quantity':1}],'tax_rate':-1})
  self.assertEqual(err.exception.code,422)
  for path in ['/','/static/app.js','/static/pos.js','/static/style.css']:self.assertTrue(self.call(path))
if __name__=='__main__':unittest.main()
