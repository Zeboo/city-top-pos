const CACHE='top-city-pos-v3';
const SHELL=['/','/static/style.css','/static/app.js','/static/pos.js'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
 const request=event.request,url=new URL(request.url);
 if(request.method!=='GET'||url.origin!==location.origin)return;
 if(url.pathname.startsWith('/api/')&&!['/api/menu','/api/me'].includes(url.pathname))return;
 event.respondWith(fetch(request).then(response=>{
  if(response.ok)caches.open(CACHE).then(cache=>cache.put(request,response.clone()));
  return response;
 }).catch(()=>caches.match(request).then(cached=>cached||caches.match('/'))));
});
