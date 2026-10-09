const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),money=n=>'Rs. '+Number(n||0).toLocaleString('en-PK',{minimumFractionDigits:2,maximumFractionDigits:2});
let menu=null,cart=[],role='cashier',user=null,activePage='pos',draft={mode:'takeaway'},busy=false;
const touchSelectMode=('ontouchstart' in window)||(navigator.maxTouchPoints||0)>0;
function closeTouchSelects(except=null){document.querySelectorAll('.touch-select.open').forEach(wrapper=>{if(wrapper!==except){wrapper.classList.remove('open');wrapper.querySelector('.touch-select-toggle').setAttribute('aria-expanded','false')}})}
function syncTouchSelect(select){const wrapper=select.closest('.touch-select');if(!wrapper)return;const selected=select.options[select.selectedIndex],toggle=wrapper.querySelector('.touch-select-toggle');toggle.textContent=selected?selected.textContent:'Select';toggle.disabled=select.disabled}
function enhanceTouchSelects(root=document){if(!touchSelectMode)return;const selects=[];if(root.nodeType===1&&root.matches('select'))selects.push(root);if(root.querySelectorAll)root.querySelectorAll('select').forEach(select=>selects.push(select));selects.forEach(select=>{if(select.dataset.touchReady)return;select.dataset.touchReady='1';const wrapper=document.createElement('div'),toggle=document.createElement('button'),options=document.createElement('div');wrapper.className='touch-select';toggle.type='button';toggle.className='touch-select-toggle';toggle.setAttribute('aria-haspopup','listbox');toggle.setAttribute('aria-expanded','false');options.className='touch-select-options';options.setAttribute('role','listbox');select.parentNode.insertBefore(wrapper,select);wrapper.appendChild(select);wrapper.appendChild(toggle);wrapper.appendChild(options);Array.prototype.forEach.call(select.options,option=>{const item=document.createElement('button');item.type='button';item.className='touch-select-option';item.textContent=option.textContent;item.disabled=option.disabled;item.setAttribute('role','option');item.onclick=event=>{event.stopPropagation();select.value=option.value;syncTouchSelect(select);closeTouchSelects();select.dispatchEvent(new Event('change',{bubbles:true}))};options.appendChild(item)});toggle.onclick=event=>{event.stopPropagation();const opening=!wrapper.classList.contains('open');closeTouchSelects(wrapper);wrapper.classList.toggle('open',opening);toggle.setAttribute('aria-expanded',String(opening));if(opening)syncTouchSelect(select)};select.addEventListener('change',()=>syncTouchSelect(select));syncTouchSelect(select)})}
document.addEventListener('click',()=>closeTouchSelects());
if(touchSelectMode){enhanceTouchSelects();new MutationObserver(records=>records.forEach(record=>Array.prototype.forEach.call(record.addedNodes,node=>{if(node.nodeType===1)enhanceTouchSelects(node)}))).observe(document.documentElement,{childList:true,subtree:true})}
async function api(url,opt={}){let r;try{r=await fetch(url,{...opt,headers:{'Content-Type':'application/json'}})}catch(cause){const error=Error('Cannot reach the server.');error.network=true;error.cause=cause;throw error}if(!r.ok){if(r.status===401)showLogin();let e=await r.json().catch(()=>({detail:'Request failed'})),error=Error(typeof e.detail==='string'?e.detail:'Please check the entered values.');error.status=r.status;throw error}return r.json()}
const post=(url,data={},method='POST')=>api(url,{method,body:JSON.stringify(data)});
function message(title,body,confirm=false){return new Promise(resolve=>{const d=$('#modal');d.innerHTML=`<h2>${esc(title)}</h2><small class="muted">Decent Pizza Live Portal</small><div class="dialog-body">${body}</div><div class="toolbar">${confirm?'<button id="cancel-dialog">Cancel</button>':''}<button class="primary" id="confirm-dialog">${confirm?'Confirm':'OK'}</button></div>`;d.onclose=()=>resolve(d.returnValue==='yes');$('#confirm-dialog').onclick=()=>d.close('yes');if(confirm)$('#cancel-dialog').onclick=()=>d.close('no');d.showModal()})}
window.addEventListener('beforeunload',e=>{if(cart.length){e.preventDefault();e.returnValue='';}});
window.addEventListener('unhandledrejection',e=>{e.preventDefault();message('Unable to complete action',esc(e.reason?.message||e.reason))});
function enterPortal(){$('#welcome').classList.add('hidden');showLogin();api('/api/me').then(showApp).catch(()=>{})}
function selectRole(r,b){role=r;document.querySelectorAll('.roles button').forEach(x=>x.classList.toggle('active',x===b))}
function showLogin(){$('#login').classList.remove('hidden');$('#app').classList.add('hidden')}
function showApp(u){user=u;ensureInventoryPage();ensureCustomersPage();$('#login').classList.add('hidden');$('#welcome').classList.add('hidden');$('#app').classList.remove('hidden');$('#user-label').textContent=u.username+' · '+u.role;document.querySelectorAll('.owner-only').forEach(x=>x.classList.toggle('hidden',u.role!=='owner'));openPage(u.role==='owner'?'dashboard':'pos')}
async function login(){try{showApp(await post('/api/login',{username:$('#username').value,password:$('#password').value,role}));$('#password').value=''}catch(e){$('#login-error').textContent=e.message}}
async function logout(){if(cart.length&&!await message('Logout','Discard the current unsaved order?',true))return;await post('/api/logout');cart=[];draft={mode:'takeaway'};menu=null;showLogin()}
function setHead(a,b){const top=$('.top'),actions=$('#page-header-actions');top.classList.toggle('hidden',!a);top.classList.remove('has-actions');while(actions.firstChild)actions.removeChild(actions.firstChild);actions.classList.add('hidden');$('#title').textContent=a;$('#subtitle').textContent=b;$('#user-label').classList.toggle('hidden',activePage!=='dashboard')}
function mountHeaderControls(...controls){const host=$('#page-header-actions'),nodes=[];controls.forEach(control=>{if(typeof control==='string')document.querySelectorAll(control).forEach(node=>nodes.push(node));else if(control)nodes.push(control)});nodes.forEach(node=>host.appendChild(node));host.classList.toggle('hidden',!nodes.length);$('.top').classList.toggle('has-actions',Boolean(nodes.length))}
function saveDraft(){if(!$('#discount'))return;for(const id of ['discount','tax','payment','cname','cphone','caddress'])draft[id]=$('#'+id).value}
function restoreDraft(){draft.discount=0;draft.tax=0;for(const id of ['discount','tax','payment','cname','cphone','caddress'])if(draft[id]!==undefined&&$('#'+id))$('#'+id).value=draft[id];if(!$('#payment').value){$('#payment').value='cash';draft.payment='cash'}$('#cphone').oninput=queueCustomerLookup;$('#cphone').onblur=lookupDeliveryCustomer;$('.pos-cart h2 span').id='cart-count';$('.pos-order-number').textContent='New order'}
async function openPage(p){if(activePage==='pos')saveDraft();activePage=p;document.querySelectorAll('.page').forEach(x=>x.classList.toggle('hidden',x.id!==p));document.querySelectorAll('[data-page]').forEach(x=>x.classList.toggle('active',x.dataset.page===p));await ({dashboard:loadDashboard,pos:loadPos,orders:()=>loadSales('orders'),reports:()=>loadSales('reports'),cashback:loadCashback,inventory:loadInventory,management:loadManagement,guests:loadGuests}[p])()}
function allMenu(){return menu.categories.flatMap(c=>c.products.map(p=>({...p,category:c.id,categoryName:c.name})))}
function setPosMode(mode){draft.mode=mode;$('#takeaway-mode').classList.toggle('active',mode==='takeaway');$('#delivery-mode').classList.toggle('active',mode==='delivery');$('#delivery-fields').classList.toggle('hidden',mode!=='delivery');$('#order-type').value=mode}
function setPosCategory(c,b){window.posCategory=c;document.querySelectorAll('.pos-categories button').forEach(x=>{let active=x===b;x.classList.toggle('active',active);x.setAttribute('aria-pressed',String(active))});renderMenu()}
function productImage(p){
 let name=String(p.name||'').toLowerCase(),n=(name+' '+(p.categoryName||'')).toLowerCase(),dealNumber=p.deal&&p.name.match(/\d+/)?.[0];
 let itemImages={
  'loaded fries regular':'loaded-fries-regular','loaded fries large':'loaded-fries-large','plain fries':'plain-fries','mayo garlic fries':'mayo-garlic-fries',
  'chicken tikka burger':'chicken-tikka-burger','chicken fajita burger':'chicken-fajita-burger','zinger burger':'zinger-burger','chicken patty burger':'chicken-patty-burger','grill cheese burger':'grill-cheese-burger','zinger cheese burger':'zinger-cheese-burger','double dose burger':'double-dose-burger',
  'chicken zinger pcs':'chicken-zinger-pcs','crispy wings 3 pcs':'crispy-wings-3pcs','crispy wings 6 pcs':'crispy-wings-6pcs','crispy wings 12 pcs':'crispy-wings-12pcs','nuggets 6 pcs':'nuggets-6pcs','nuggets 12 pcs':'nuggets-12pcs',
  'club sandwich':'club-sandwich','tikka sandwich':'tikka-sandwich','grill cheese sandwich':'grill-cheese-sandwich',
  'coca-cola':'coca-cola','7up':'7up','sprite':'sprite','next cola':'next-cola-branded','fizzup':'fizzup',
  'tikka pizza':'tikka-pizza','fajita pizza':'fajita-pizza','kabab pizza':'kabab-pizza','cheese lover':'cheese-lover-pizza','hot & spicy pizza':'hot-spicy-pizza','bbq pizza':'bbq-pizza','vegetable pizza':'vegetable-pizza','all topping':'all-topping-pizza','malai boti pizza':'malai-boti-pizza','special decent pizza':'special-decent-pizza','crown crust':'crown-crust-pizza'
 };
 let labeledDeals=new Set(Array.from({length:24},(_,i)=>String(i+1)));
 let file=dealNumber?`deal-${dealNumber}${labeledDeals.has(dealNumber)?'-labeled':''}`:itemImages[name]||(
  n.includes('drink')?'next-cola':n.includes('pasta')?'pasta':n.includes('sandwich')?'sandwich':n.includes('wrap')?'wrap':n.includes('burger')?'burger':n.includes('shawarma')?'shawarma':n.includes('roll')||n.includes('paratha')?'roll':n.includes('fries')?'fries':n.includes('wing')||n.includes('nugget')||n.includes('starter')||n.includes('zinger pcs')?'sides':'pizza');
 return `/resources/images/menu/${file}.png`
}
function dealCard(p){return `<article id="deal-${p.id}" class="product product-card deal-card" style="--deal-image:url('${productImage(p)}')"><div class="deal-overlay" aria-hidden="true"></div><div class="product-top"><h3>${esc(p.name)}</h3></div><div class="product-description">${esc(p.description)}</div><div class="product-chips"><span class="size-chip">SPECIAL DEAL</span></div><div class="product-bottom"><b class="product-price">${money(p.price)}</b><button class="add-round" aria-label="Add ${esc(p.name)}" onclick="addDeal(${p.id})">+</button></div></article>`}
function productCard(p){return `<article id="product-${p.id}" class="product product-card regular-card" style="--menu-image:url('${productImage(p)}')"><div class="menu-overlay" aria-hidden="true"></div><div class="product-top"><h3>${esc(p.name)}</h3></div><div class="product-description">${esc(p.description)}</div><div class="product-chips">${p.variants.map(v=>`<span class="size-chip">${esc(v.name)}</span>`).join('')}</div><div class="product-bottom"><b class="product-price">${money(Math.min(...p.variants.map(v=>v.price)))}${p.variants.length>1?' onward':''}</b><button class="add-round" aria-label="Add ${esc(p.name)}" onclick="chooseSize(${p.id})">+</button></div></article>`}
function renderMenu(){let term=$('#menu-search').value.toLowerCase(),cat=window.posCategory||'';let items=cat==='deals'?menu.deals.map(d=>({...d,deal:true})):allMenu().filter(p=>!cat||String(p.category)===cat);items=items.filter(p=>(p.name+' '+p.description).toLowerCase().includes(term));let grid=$('#menu-grid');grid.classList.toggle('deals-grid',cat==='deals');grid.classList.toggle('products-grid',cat!=='deals');grid.innerHTML=items.map(p=>p.deal?dealCard(p):productCard(p)).join('')||'<div class="empty">No menu items found.</div>'}
function chooseSize(id){let p=allMenu().find(p=>p.id===id);if(p.variants.length===1)return addProduct(p.variants[0].id);let card=$('#product-'+id),existing=card.querySelector('.size-expansion');if(existing){existing.remove();return}card.insertAdjacentHTML('beforeend',`<div class="size-expansion"><div class="size-options">${p.variants.map((v,i)=>`<button class="${i===0?'selected':''}" data-variant="${v.id}" onclick="this.parentNode.querySelectorAll('button').forEach(b=>b.classList.remove('selected'));this.classList.add('selected')"><span class="size-option-name">${esc(v.name)}</span><b class="size-option-price">${money(v.price)}</b></button>`).join('')}</div><button class="primary" onclick="addProduct(Number(this.parentNode.querySelector('.selected').dataset.variant));this.parentNode.remove()">Add to order</button></div>`)}
function categoryClass(label){let n=label.toLowerCase();return n.includes('pizza')?'pizza':n.includes('deal')?'deals':n.includes('fries')||n.includes('side')?'fries':n.includes('drink')?'drinks':n.includes('burger')?'burgers':n.includes('shawarma')?'shawarma':n.includes('roll')||n.includes('paratha')?'roll':n.includes('wrap')?'wrap':n.includes('pasta')?'pasta':n.includes('sandwich')?'sandwich':n.includes('starter')?'starters':'other'}
function desktopCategories(){let labels={'Classic Pizzas':'Pizza','Specialty Pizzas':'Pizza','Sides':'Fries'},seen=new Set(),entries=[];for(let c of menu.categories){if(c.name==='Deals')continue;let label=labels[c.name]||c.name;if(seen.has(label))continue;seen.add(label);entries.push({id:String(c.id),label})}entries.splice(Math.min(1,entries.length),0,{id:'deals',label:'Deals'});window.posCategory=entries[0]?.id||'deals';$('.pos-categories').innerHTML=entries.map((c,i)=>`<button class="category-tab category-${categoryClass(c.label)} ${i===0?'active':''}" aria-pressed="${i===0}" onclick="setPosCategory('${c.id}',this)">${esc(c.label)}</button>`).join('')}

function addProduct(id){let x=cart.find(x=>x.variant_id===id);if(x){if(x.quantity<100)x.quantity++}else cart.push({variant_id:id,quantity:1});renderCart()}
function addDeal(id){let x=cart.find(x=>x.deal_id===id);if(x){if(x.quantity<100)x.quantity++}else cart.push({deal_id:id,quantity:1});renderCart()}
function lineInfo(x){if(x.deal_id)return menu.deals.find(d=>d.id===x.deal_id)||{name:'Unavailable deal',price:0};let p=allMenu().find(p=>p.variants.some(v=>v.id===x.variant_id));let v=p?.variants.find(v=>v.id===x.variant_id);return v?{name:p.name+' · '+v.name,price:v.price}:{name:'Unavailable item',price:0}}
function adjust(i,n){cart[i].quantity+=n;if(cart[i].quantity<=0)cart.splice(i,1);else cart[i].quantity=Math.min(100,cart[i].quantity);renderCart()}
function clearCart(){cart=[];$('#discount').value=0;$('#tax').value=0;renderCart()}
function renderCart(){if(!$('#cart-lines'))return;let subtotal=cart.reduce((s,x)=>s+Number(lineInfo(x).price)*x.quantity,0);$('#cart-lines').innerHTML=cart.map((x,i)=>`<div class="cart-line"><span>${esc(lineInfo(x).name)}<br><button onclick="adjust(${i},-1)">−</button> ${x.quantity} <button onclick="adjust(${i},1)">+</button></span><b>${money(lineInfo(x).price*x.quantity)}</b><button onclick="cart.splice(${i},1);renderCart()">Remove</button></div>`).join('')||'<div class="pos-empty">⊘<span>No items yet. Tap a pizza or<br>deal to start this order.</span></div>';$('.pos-cart').classList.toggle('empty-cart',!cart.length);$('#cart-count').textContent=cart.reduce((n,x)=>n+x.quantity,0);let discount=Math.min(subtotal,Math.max(0,Number($('#discount').value)||0)),tax=Math.max(0,Math.min(100,Number($('#tax').value)||0));$('#cart-total').innerHTML=`<small>SUBTOTAL ${money(subtotal)}</small><br>${money(subtotal-discount+Math.round((subtotal-discount)*tax)/100)}`;$('#discount').placeholder='Discount · Rs.';$('#tax').placeholder='Tax · %';$('.cart .toolbar').innerHTML='<button onclick="clearCart()">Clear</button><button class="primary" onclick="submitOrder()">CHECKOUT</button>';saveDraft()}
async function submitOrder(){if(busy)return;if(!cart.length)return message('Empty order','Add an item first.');saveDraft();const payload={lines:cart.map(x=>({...x})),order_type:draft.mode,payment_method:draft.payment||'cash',discount:Number(draft.discount||0),tax_rate:Number(draft.tax||0),customer_name:draft.cname,customer_phone:draft.cphone,customer_address:draft.caddress};if(draft.mode==='delivery'&&![draft.cname,draft.cphone,draft.caddress].every(v=>v?.trim()))return message('Delivery details','Receiver name, phone and address are required.');busy=true;try{if(!await message('Confirm checkout',`<p>Payment: ${esc(payload.payment_method)}</p><b>${$('#cart-total').innerHTML}</b>`,true))return;let o=await post('/api/orders',payload);clearCart();let body=`<div id="receipt"><h2>DECENT PIZZA LIVE</h2><b>${esc(o.order_number)}</b><p>${esc(o.order_type)} · ${esc(o.payment_method)}</p>${o.order_type==='delivery'?`<p>${esc(payload.customer_name)}<br>${esc(payload.customer_phone)}<br>${esc(payload.customer_address)}</p>`:''}<hr><p>Subtotal: ${money(o.subtotal)}<br>Discount: ${money(o.discount)}<br>Tax: ${money(o.tax)}<br><b>Total: ${money(o.total)}</b></p><p>Thank you for your order.</p></div><button onclick="printReceiptPair(this.previousElementSibling)">Print receipt</button>`;await message('Sale receipt',body)}finally{busy=false}}
function filters(prefix,status=false){return `<div class="toolbar ${prefix}-filters"><label>Sales period: <select id="${prefix}-period">${['All dates','Today','Specific date','This week','This month'].map(x=>`<option>${x}</option>`).join('')}</select></label><input id="${prefix}-date" type="date" value="${new Date().toLocaleDateString('en-CA')}" class="hidden">${status?`<select id="${prefix}-status"><option value="all">All statuses</option><option value="awaiting">Awaiting approval</option><option value="approved">Approved</option><option value="cashback">Pending / cashback</option><option value="denied">Rejected</option></select><select id="${prefix}-sort"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="highest">Highest amount</option><option value="lowest">Lowest amount</option><option value="number">Order number A-Z</option></select><input id="${prefix}-search" placeholder="Search order, type, or payment...">`:''}</div>`}
function query(p){let q=new URLSearchParams({period:$('#'+p+'-period').value}),specific=q.get('period')==='Specific date';$('#'+p+'-date').classList.toggle('hidden',!specific);$('#'+p+'-period').closest('.toolbar')?.classList.toggle('specific-date',specific);if(specific)q.set('selected_date',$('#'+p+'-date').value);for(let k of ['status','sort','search'])if($('#'+p+'-'+k))q.set(k,$('#'+p+'-'+k).value);return q}
function stats(s){return `<div class="cards">${[['Net sales',money(s.net_sales)],['Gross sales',money(s.gross_sales)],['Cash payments',money(s.cash)],['Online payments',money(s.online)],['Recorded orders',s.orders],['Cashback deducted',money(s.cashback)],['Awaiting approval',s.awaiting]].map(([l,v])=>`<div class="card"><small>${l}</small><div class="value">${v}</div></div>`).join('')}</div>`}
async function loadDashboard(){setHead('Business dashboard','Sales overview');$('#dashboard').innerHTML=filters('dash')+'<div id="dash-data"></div><button class="primary start-order" onclick="openPage(\'pos\')">＋ START NEW ORDER</button>';document.querySelectorAll('#dashboard input,#dashboard select').forEach(x=>x.onchange=refreshDashboard);mountHeaderControls('.dash-filters');await refreshDashboard()}
async function refreshDashboard(){let d=await api('/api/dashboard?'+query('dash')),s=d.summary;$('#dash-data').innerHTML=stats(s)+`<div class="columns dashboard-panels"><div class="panel"><h2>Top-selling items</h2>${d.top_items.slice(0,5).map((x,i)=>`<div class="row"><b>${i+1}</b><span>${esc(x.name)}</span><small>${x.quantity} sold</small></div>`).join('')||'No approved sales yet'}</div><div class="panel"><h2>Payment breakdown</h2><div class="cash-bar"></div>${[['Cash',s.cash],['Card',s.card],['Online',s.online],['Cashback deducted',s.cashback]].map(([l,v])=>`<p>${l} · ${money(v)}</p>`).join('')}</div></div>`}
async function loadSales(p){setHead(p==='orders'?'Order history':'Sales reports',p==='orders'?'All saved sales remain available here after the app is closed.':'A live view of approved and pending sales.');$('#'+p).innerHTML=filters(p,true)+`<div class="toolbar ${p}-actions"><button onclick="refreshSales('${p}')">Refresh</button>${p==='reports'?'<button onclick="printSalesReport()">Print sales list</button><a class="button" id="pdf">Export PDF</a>':''}</div><div id="${p}-stats"></div><div class="list" id="${p}-list"></div>`;document.querySelectorAll('#'+p+' select,#'+p+' input').forEach(x=>x.onchange=()=>refreshSales(p));$('#'+p+'-search').oninput=()=>refreshSales(p);mountHeaderControls('.'+p+'-filters','.'+p+'-actions');await refreshSales(p)}
let salesRequest=0;
async function refreshSales(p){const ticket=++salesRequest,q=query(p);let [rows,d]=await Promise.all([api('/api/orders?'+q),api('/api/dashboard?'+q)]);if(ticket!==salesRequest)return;$('#'+p+'-stats').innerHTML=stats(d.summary);if(p==='reports')$('#pdf').href='/api/reports.pdf?'+q;$('#'+p+'-list').innerHTML=rows.map(o=>`<div class="row ${p==='orders'?'order-row':''}" ${p==='orders'?`role="button" tabindex="0" onclick="openOrderDetail(${o.id})" onkeydown="if(event.key==='Enter')openOrderDetail(${o.id})"`:''}><span class="grow"><b>Order No-${esc(receiptOrderNumber(o.order_number))}</b><br><small>${esc(o.order_type)} · ${esc(o.payment_method)}</small>${orderDateTimeMarkup(o.created_at)}</span><b>Net ${money(o.net_total)}</b><span class="badge ${esc(o.approval_status)}">${esc(o.approval_status==='denied'?'rejected':o.approval_status)}</span>${p==='orders'&&o.approval_status==='awaiting'?`<span class="order-actions" onclick="event.stopPropagation()"><button class="approve" onclick="setStatus(${o.id},'approved')">Approve</button><button class="pending" onclick="setStatus(${o.id},'pending')">Pending</button><button class="deny" onclick="setStatus(${o.id},'denied')">Reject</button></span>`:''}</div>`).join('')||'<div class="empty">No sales recorded yet.</div>'}
async function setStatus(id,status){await post('/api/orders/'+id+'/status',{status});await refreshSales('orders')}
async function openOrderDetail(id){
 const order=await api('/api/orders/'+id),dialog=$('#modal');
 const status=order.approval_status==='denied'?'rejected':order.approval_status;
 const customer=order.customer?`<section class="order-detail-customer"><h3>Customer &amp; delivery</h3><p><b>${esc(order.customer.name)}</b><br>${esc(order.customer.phone)}<br>${esc(order.customer.address)}</p></section>`:'';
 const items=order.items.map(item=>`<tr><td>${esc(item.name)}</td><td>${item.quantity}</td><td>${money(item.unit_price)}</td><td>${money(item.total)}</td></tr>`).join('')||'<tr><td colspan="4">No line items available.</td></tr>';
 dialog.innerHTML=`<div class="order-detail-heading"><div><small>ORDER DETAILS</small><h2>Order No-${esc(receiptOrderNumber(order.order_number))}</h2></div><span class="badge ${esc(order.approval_status)}">${esc(status)}</span></div><div class="order-detail-meta"><span><small>Created</small><b>${orderDateTimeMarkup(order.created_at)}</b></span><span><small>Order type</small><b>${esc(order.order_type)}</b></span><span><small>Payment</small><b>${esc(order.payment_method)}</b></span></div>${customer}<h3>Items</h3><div class="order-detail-table-wrap"><table class="order-detail-table"><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Total</th></tr></thead><tbody>${items}</tbody></table></div><div class="order-detail-totals"><span>Subtotal <b>${money(order.subtotal)}</b></span><span>Discount <b>${money(order.discount)}</b></span><span>Tax <b>${money(order.tax)}</b></span><span class="order-detail-grand">Total <b>${money(order.total)}</b></span></div><div class="toolbar order-detail-actions">${order.approval_status==='awaiting'?`<button class="approve" id="detail-approve">Approve order</button><button class="deny" id="detail-reject">Reject order</button>`:''}<button class="gold" id="detail-print">Print receipt</button><button id="detail-close">Close</button></div>`;
 dialog.querySelector('#detail-close').onclick=()=>dialog.close();
 const decide=async status=>{await post('/api/orders/'+id+'/status',{status});dialog.close();await refreshSales('orders')};
 if($('#detail-approve'))$('#detail-approve').onclick=()=>decide('approved');
 if($('#detail-reject'))$('#detail-reject').onclick=()=>decide('denied');
 $('#detail-print').onclick=()=>printOrderReceipt(order);
 dialog.showModal();
}
function cashbackFilters(){return `<div class="toolbar cashback-filters"><label>Cashback period: <select id="cashback-period">${['All dates','Today','Specific date','This week','This month'].map(x=>`<option>${x}</option>`).join('')}</select></label><input id="cashback-date" type="date" value="${new Date().toLocaleDateString('en-CA')}" class="hidden"><input id="cashback-search" placeholder="Search order, customer, type or payment..."><select id="cashback-status"><option value="all">All cashback statuses</option><option value="pending">Pending approval</option><option value="approved">Approved</option></select><select id="cashback-sort"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="highest">Highest cashback</option><option value="lowest">Lowest cashback</option><option value="name">Customer name A-Z</option><option value="type">Order type A-Z</option><option value="payment">Payment method A-Z</option><option value="number">Order number A-Z</option></select><button onclick="refreshCashback()">Refresh</button></div>`}
function cashbackDate(value){if(!value)return 'Date unavailable';let d=new Date(value);return Number.isNaN(d.getTime())?esc(value):d.toLocaleString([],{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
function cashbackRow(o,latest=false){return `<div class="row cashback-row${latest?' cashback-latest-row':''}"><span class="grow">${latest?'<span class="latest-label">Newest cashback record</span>':''}<b>${esc(o.order_number)}</b><br><small>${esc(o.customer_name)} · ${esc(o.order_type)} · ${esc(o.payment_method)}<br>Moved to cashback: <time datetime="${esc(o.cashback_date||'')}">${cashbackDate(o.cashback_date)}</time></small></span><b>${money(o.cashback_amount)}</b><span class="badge ${esc(o.cashback_status)}">${esc(o.cashback_status)}</span>${o.cashback_status==='pending'?`<button class="approve" onclick="approveCashback(${o.id})">Approve cashback</button>`:''}</div>`}
let cashbackRequest=0;
async function loadCashback(){setHead('Cashback','Filter cashback records by date, customer, order type, payment and status.');$('#cashback').innerHTML=cashbackFilters()+`<div id="cashback-summary"></div><section id="cashback-newest"></section><section class="cashback-history"><h2>Cashback history</h2><div class="list" id="cashback-list"></div></section>`;document.querySelectorAll('#cashback select,#cashback input').forEach(x=>x.onchange=refreshCashback);$('#cashback-search').oninput=refreshCashback;mountHeaderControls('.cashback-filters');await refreshCashback()}
async function refreshCashback(){const ticket=++cashbackRequest,q=query('cashback'),x=await api('/api/cashback?'+q);if(ticket!==cashbackRequest)return;let pendingTotal=x.pending.reduce((s,o)=>s+o.cashback_amount,0),approvedTotal=x.approved.reduce((s,o)=>s+o.cashback_amount,0),newest=x.newest,history=newest?x.records.filter(o=>o.id!==newest.id):x.records;$('#cashback-summary').innerHTML=`<div class="cards cashback-summary"><div class="card"><small>Matching records</small><div class="value">${x.records.length}</div></div><div class="card"><small>Pending cashback</small><div class="value">${money(pendingTotal)}</div></div><div class="card"><small>Approved cashback</small><div class="value">${money(approvedTotal)}</div></div></div>`;$('#cashback-newest').innerHTML=newest?cashbackRow(newest,true):'';$('.cashback-history').classList.toggle('hidden',!newest);$('#cashback-list').innerHTML=history.map(o=>cashbackRow(o)).join('')||'<div class="empty">No earlier cashback records for the selected filters.</div>'}
async function approveCashback(id){await post('/api/cashback/'+id+'/approve');await refreshCashback()}

/* Clickable cashback workflow with persistent approve/reject decisions. */
cashbackFilters=function(){return `<div class="toolbar cashback-filters"><label>Cashback period: <select id="cashback-period">${['All dates','Today','Specific date','This week','This month'].map(x=>`<option>${x}</option>`).join('')}</select></label><input id="cashback-date" type="date" value="${new Date().toLocaleDateString('en-CA')}" class="hidden"><input id="cashback-search" placeholder="Search order, customer, type or payment..."><select id="cashback-status"><option value="all">All cashback statuses</option><option value="pending">Pending approval</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select><select id="cashback-sort"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="highest">Highest cashback</option><option value="lowest">Lowest cashback</option><option value="name">Customer name A-Z</option><option value="type">Order type A-Z</option><option value="payment">Payment method A-Z</option><option value="number">Order number A-Z</option></select><button onclick="refreshCashback()">Refresh</button></div>`};
cashbackRow=function(o,latest=false){return `<div class="row cashback-row${latest?' cashback-latest-row':''}" role="button" tabindex="0" onclick="openCashbackDetail(${o.id})" onkeydown="if(event.key==='Enter')openCashbackDetail(${o.id})"><span class="grow">${latest?'<span class="latest-label">Newest cashback record</span>':''}<b>Order No-${esc(receiptOrderNumber(o.order_number))}</b><br><small>${esc(o.customer_name)} &middot; ${esc(o.order_type)} &middot; ${esc(o.payment_method)}</small>${orderDateTimeMarkup(o.cashback_date||o.created_at)}</span><b>${money(o.cashback_amount)}</b><span class="badge ${esc(o.cashback_status)}">${esc(o.cashback_status)}</span>${o.cashback_status==='pending'?`<span class="cashback-row-actions" onclick="event.stopPropagation()"><button class="approve" onclick="approveCashback(${o.id})">Approve cashback</button><button class="deny" onclick="rejectCashback(${o.id})">Reject</button></span>`:''}</div>`};
refreshCashback=async function(){const ticket=++cashbackRequest,q=query('cashback'),x=await api('/api/cashback?'+q);if(ticket!==cashbackRequest)return;let pendingTotal=x.pending.reduce((s,o)=>s+o.cashback_amount,0),approvedTotal=x.approved.reduce((s,o)=>s+o.cashback_amount,0),newest=x.newest,history=newest?x.records.filter(o=>o.id!==newest.id):x.records;$('#cashback-summary').innerHTML=`<div class="cards cashback-summary"><div class="card"><small>Matching records</small><div class="value">${x.records.length}</div></div><div class="card"><small>Pending cashback</small><div class="value">${money(pendingTotal)}</div></div><div class="card"><small>Approved cashback</small><div class="value">${money(approvedTotal)}</div></div><div class="card"><small>Rejected</small><div class="value">${x.rejected.length}</div></div></div>`;$('#cashback-newest').innerHTML=newest?cashbackRow(newest,true):'';$('.cashback-history').classList.toggle('hidden',!newest);$('#cashback-list').innerHTML=history.map(o=>cashbackRow(o)).join('')||'<div class="empty">No earlier cashback records for the selected filters.</div>'};
async function rejectCashback(id){await post('/api/cashback/'+id+'/reject');await refreshCashback()}
async function openCashbackDetail(id){
 const order=await api('/api/orders/'+id),dialog=$('#modal');
 const customer=order.customer?`<section class="order-detail-customer"><h3>Customer &amp; delivery</h3><p><b>${esc(order.customer.name)}</b><br>${esc(order.customer.phone)}<br>${esc(order.customer.address)}</p></section>`:'<section class="order-detail-customer"><h3>Customer</h3><p>Walk-in customer</p></section>';
 const items=order.items.map(item=>`<tr><td>${esc(item.name)}</td><td>${item.quantity}</td><td>${money(item.unit_price)}</td><td>${money(item.total)}</td></tr>`).join('')||'<tr><td colspan="4">No line items available.</td></tr>';
 dialog.innerHTML=`<div class="order-detail-heading"><div><small>CASHBACK DETAILS</small><h2>Order No-${esc(receiptOrderNumber(order.order_number))}</h2></div><span class="badge ${esc(order.cashback_status)}">${esc(order.cashback_status)}</span></div><div class="order-detail-meta"><span><small>Cashback date</small><b>${orderDateTimeMarkup(order.cashback_created_at||order.created_at)}</b></span><span><small>Order type</small><b>${esc(order.order_type)}</b></span><span><small>Payment</small><b>${esc(order.payment_method)}</b></span></div>${customer}<h3>Order items</h3><div class="order-detail-table-wrap"><table class="order-detail-table"><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Total</th></tr></thead><tbody>${items}</tbody></table></div><div class="order-detail-totals"><span>Order total <b>${money(order.total)}</b></span><span class="cashback-detail-amount">Cashback amount <b>${money(order.cashback_amount)}</b></span><span class="order-detail-grand">Net after cashback <b>${money(order.net_total)}</b></span></div><div class="toolbar order-detail-actions">${order.cashback_status==='pending'?`<button class="approve" id="cashback-detail-approve">Approve cashback</button><button class="deny" id="cashback-detail-reject">Reject cashback</button>`:''}<button id="cashback-detail-close">Close</button></div>`;
 $('#cashback-detail-close').onclick=()=>dialog.close();
 const decide=async action=>{await post('/api/cashback/'+id+'/'+action);dialog.close();await refreshCashback()};
 if($('#cashback-detail-approve'))$('#cashback-detail-approve').onclick=()=>decide('approve');
 if($('#cashback-detail-reject'))$('#cashback-detail-reject').onclick=()=>decide('reject');
 const printButton=document.createElement('button');
 printButton.className='gold';
 printButton.textContent='Print receipt';
 printButton.onclick=()=>printCashbackReceipt(order);
 dialog.querySelector('.order-detail-actions').insertBefore(printButton,$('#cashback-detail-close'));
 dialog.showModal();
}

function ensureInventoryPage(){if($('#inventory'))return;let management=document.querySelector('[data-page="management"]');management.insertAdjacentHTML('beforebegin',`<button class="nav owner-only" data-page="inventory" onclick="openPage('inventory')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7 12 3l8 4-8 4-8-4Z"/><path d="M4 7v10l8 4 8-4V7M12 11v10"/></svg><span>Inventory</span></button>`);document.querySelector('main').insertAdjacentHTML('beforeend','<section id="inventory" class="page hidden"></section>')}
let inventoryData=null,selectedInventory=null;
async function loadInventory(){setHead('Inventory management','Track ingredients, purchases, usage, waste and low-stock levels.');$('#inventory').innerHTML=`<div class="toolbar inventory-tabs"><button onclick="inventoryTab('stock')">Stock</button><button onclick="inventoryTab('recipes')">Recipes</button><button onclick="inventoryTab('history')">Movement history</button></div><div id="inventory-content"></div>`;mountHeaderControls('.inventory-tabs');await refreshInventory('stock')}
function inventoryTab(tab){renderInventory(tab)}
async function refreshInventory(tab='stock'){inventoryData=await api('/api/inventory');renderInventory(tab)}
function renderInventory(tab){let x=inventoryData;if(tab==='stock'){$('#inventory-content').innerHTML=`<div class="cards inventory-summary"><div class="card"><small>Active items</small><div class="value">${x.summary.items}</div></div><div class="card"><small>Low stock</small><div class="value">${x.summary.low}</div></div><div class="card"><small>Stock value</small><div class="value">${money(x.summary.value)}</div></div></div><div class="inventory-layout"><form class="panel form" onsubmit="event.preventDefault();saveInventoryItem()"><h2 id="inventory-form-title">Add stock item</h2><label>Name<input id="inv-name" required></label><label>SKU<input id="inv-sku"></label><label>Unit<select id="inv-unit"><option>pcs</option><option>kg</option><option>g</option><option>liter</option><option>ml</option><option>pack</option></select></label><label>Current quantity<input id="inv-qty" type="number" min="0" step=".001" value="0"></label><label>Reorder level<input id="inv-reorder" type="number" min="0" step=".001" value="0"></label><label>Unit cost<input id="inv-cost" type="number" min="0" step=".01" value="0"></label><label>Supplier<input id="inv-supplier"></label><button class="primary">SAVE ITEM</button><button type="button" onclick="clearInventoryForm()">CLEAR</button></form><div><div class="toolbar"><input id="inv-search" placeholder="Search name, SKU or supplier..." oninput="filterInventory()"><button class="gold" onclick="adjustSelectedInventory()">ADJUST STOCK</button><button class="deny" onclick="deleteSelectedInventory()">DELETE ITEM</button></div><div class="inventory-list-head"><span>Item details</span><span>Stock</span><span>Cost & value</span><span>Status / actions</span></div><div id="inventory-list" class="list">${inventoryRows(x.items)}</div></div></div>`}else if(tab==='recipes'){let targets=x.products.map(p=>`<option value="product:${p.id}">Product · ${esc(p.name)}</option>`).join('')+x.deals.map(d=>`<option value="deal:${d.id}">Deal · ${esc(d.name)}</option>`).join('');$('#inventory-content').innerHTML=`<div class="columns"><form class="panel form" onsubmit="event.preventDefault();saveRecipe()"><h2>Link stock to menu</h2><label>Menu product / deal<select id="recipe-target">${targets}</select></label><label>Inventory item<select id="recipe-item">${x.items.map(i=>`<option value="${i.id}">${esc(i.name)} (${esc(i.unit)})</option>`).join('')}</select></label><label>Used per sale<input id="recipe-qty" type="number" min=".001" step=".001" required></label><button class="primary">ADD RECIPE LINE</button><p class="muted">Each checkout deducts this quantity automatically.</p></form><div class="list">${x.recipes.map(r=>`<div class="row"><span><b>${esc(r.target)}</b><br><small>${esc(r.item)} · ${r.quantity} per sale</small></span><span class="badge">${r.target_type}</span><button class="deny" onclick="deleteRecipe(${r.id})">Remove</button></div>`).join('')||'<div class="empty">No recipes configured yet.</div>'}</div></div>`}else{$('#inventory-content').innerHTML=`<div class="list">${x.movements.map(m=>`<div class="row"><span><b>${esc(m.item)}</b><br><small>${new Date(m.created_at).toLocaleString()} · ${esc(m.notes)}</small></span><b class="${m.quantity<0?'stock-out':'stock-in'}">${m.quantity>0?'+':''}${m.quantity}</b><span class="badge">${esc(m.type)}</span></div>`).join('')||'<div class="empty">No stock movements yet.</div>'}</div>`}}
function inventoryRows(items){return items.map(i=>`<div class="row inventory-item ${selectedInventory?.id===i.id?'selected':''} ${i.low_stock?'low-stock':''}"><button class="inventory-select" onclick="selectInventory(${i.id})"><span><b>${esc(i.name)}</b><small>SKU: ${esc(i.sku||'Not assigned')}<br>Supplier: ${esc(i.supplier||'Not assigned')}</small></span><span><b>${i.quantity} ${esc(i.unit)}</b><small>Reorder level: ${i.reorder_level} ${esc(i.unit)}</small></span><span><b>${money(i.unit_cost)} / ${esc(i.unit)}</b><small>Total value: ${money(i.quantity*i.unit_cost)}</small></span><span><span class="badge ${i.low_stock?'pending':'approved'}">${i.low_stock?'LOW STOCK':'IN STOCK'}</span><small>Click to edit</small></span></button><div class="inventory-actions"><button onclick="selectInventory(${i.id})">Edit</button><button class="deny" onclick="deleteInventory(${i.id})">Delete</button></div></div>`).join('')||'<div class="empty">Add your first inventory item.</div>'}
function filterInventory(){let q=$('#inv-search').value.toLowerCase();$('#inventory-list').innerHTML=inventoryRows(inventoryData.items.filter(i=>(i.name+' '+i.sku+' '+i.supplier).toLowerCase().includes(q)))}
function selectInventory(id){selectedInventory=inventoryData.items.find(i=>i.id===id);$('#inv-name').value=selectedInventory.name;$('#inv-sku').value=selectedInventory.sku;$('#inv-unit').value=selectedInventory.unit;$('#inv-qty').value=selectedInventory.quantity;$('#inv-qty').disabled=false;$('#inv-reorder').value=selectedInventory.reorder_level;$('#inv-cost').value=selectedInventory.unit_cost;$('#inv-supplier').value=selectedInventory.supplier;$('#inventory-form-title').textContent='Edit '+selectedInventory.name;$('#inventory-list').innerHTML=inventoryRows(inventoryData.items)}
function clearInventoryForm(){selectedInventory=null;for(const id of ['inv-name','inv-sku','inv-supplier'])$('#'+id).value='';for(const id of ['inv-qty','inv-reorder','inv-cost'])$('#'+id).value=0;$('#inv-qty').disabled=false;$('#inventory-form-title').textContent='Add stock item'}
async function saveInventoryItem(){let p={name:$('#inv-name').value,sku:$('#inv-sku').value||null,unit:$('#inv-unit').value,quantity:Number($('#inv-qty').value||0),reorder_level:Number($('#inv-reorder').value||0),unit_cost:Number($('#inv-cost').value||0),supplier:$('#inv-supplier').value||null};await post('/api/inventory/items'+(selectedInventory?'/'+selectedInventory.id:''),p,selectedInventory?'PUT':'POST');selectedInventory=null;await refreshInventory('stock')}
async function adjustSelectedInventory(){if(!selectedInventory)return message('Select stock item','Select an inventory row first.');let amount=prompt(`Enter quantity change for ${selectedInventory.name}. Use a negative number for usage or waste.`);if(amount===null||!Number(amount))return;let notes=prompt('Reason / reference:')||'';await post(`/api/inventory/items/${selectedInventory.id}/adjust`,{quantity:Number(amount),movement_type:Number(amount)>0?'purchase':'adjustment',notes});selectedInventory=null;await refreshInventory('stock')}
async function deleteSelectedInventory(){if(!selectedInventory)return message('Select stock item','Select an inventory row first.');await deleteInventory(selectedInventory.id)}
async function deleteInventory(id){let item=inventoryData.items.find(i=>i.id===id);if(!await message('Delete inventory item',`Permanently delete <b>${esc(item?.name||'this item')}</b>, its recipe links, and its movement history?`,true))return;await api('/api/inventory/items/'+id,{method:'DELETE'});selectedInventory=null;await refreshInventory('stock')}
async function saveRecipe(){let [type,id]=$('#recipe-target').value.split(':');await post('/api/inventory/recipes',{inventory_item_id:Number($('#recipe-item').value),product_id:type==='product'?Number(id):null,deal_id:type==='deal'?Number(id):null,quantity_required:Number($('#recipe-qty').value)});await refreshInventory('recipes')}
async function deleteRecipe(id){if(await message('Remove recipe line','Stop deducting this stock item for the selected menu item?',true)){await api('/api/inventory/recipes/'+id,{method:'DELETE'});await refreshInventory('recipes')}}
function ensureCustomersPage(){let button=document.querySelector('[data-page="guests"]');if(!button)return;button.classList.remove('owner-only');button.querySelector('span').textContent='Customers'}
let editingCustomerId=null,customerDirectory=[];
async function loadGuests(){setHead('Customers','Save delivery details for faster repeat orders.');$('#guests').innerHTML=`<div class="columns"><form class="panel form" onsubmit="event.preventDefault();addGuest()"><div class="customer-form-heading"><h2 id="customer-form-title">Add customer</h2><button type="button" id="customer-edit-cancel" class="hidden" onclick="clearCustomerEdit()">Cancel edit</button></div><label>Name<input id="guest-name" required></label><label>Phone number<input id="guest-phone" type="tel" required placeholder="03XX XXXXXXX"></label><label>Email (optional)<input id="guest-email" type="email"></label><label>Delivery address<input id="guest-address" required></label><button class="primary" id="customer-save-button">ADD / UPDATE CUSTOMER</button><p class="muted">An existing phone number updates that customer instead of creating a duplicate.</p></form><div><h2>Customer directory</h2><input id="guest-search" placeholder="Search name, phone or email..."><div id="guest-list" class="list"></div></div></div>`;$('#guest-search').oninput=refreshGuests;mountHeaderControls($('#guest-search'));await refreshGuests()}
async function refreshGuests(){customerDirectory=await api('/api/customers?search='+encodeURIComponent($('#guest-search').value));$('#guest-list').innerHTML=customerDirectory.map(g=>`<div class="row customer-row"><span class="grow"><b>${esc(g.name)}</b><br><small>${esc(g.phone||'No phone recorded')}<br>${esc(g.address||'No delivery address')}${g.email?'<br>'+esc(g.email):''}</small></span><span class="badge approved">CUSTOMER</span><span class="customer-actions"><button onclick="editGuest(${g.id})">Edit</button><button class="deny" onclick="deleteGuest(${g.id})">Delete</button></span></div>`).join('')||'<div class="empty">No customers found.</div>'}
function editGuest(id){const customer=customerDirectory.find(item=>item.id===id);if(!customer)return;editingCustomerId=id;for(const key of ['name','phone','email','address'])$('#guest-'+key).value=customer[key]||'';$('#customer-form-title').textContent='Edit customer';$('#customer-save-button').textContent='SAVE CUSTOMER CHANGES';$('#customer-edit-cancel').classList.remove('hidden');$('#guest-name').focus();$('#guests').scrollIntoView({behavior:'smooth',block:'start'})}
function clearCustomerEdit(){$('#guests form').reset();editingCustomerId=null;$('#customer-form-title').textContent='Add customer';$('#customer-save-button').textContent='ADD / UPDATE CUSTOMER';$('#customer-edit-cancel').classList.add('hidden')}
async function addGuest(){const payload=Object.fromEntries(['name','phone','email','address'].map(k=>[k,$('#guest-'+k).value]));await post(editingCustomerId?'/api/customers/'+editingCustomerId:'/api/customers',payload,editingCustomerId?'PUT':'POST');clearCustomerEdit();await refreshGuests()}
async function deleteGuest(id){const customer=customerDirectory.find(item=>item.id===id);if(!customer||!await message('Delete customer',`Delete <b>${esc(customer.name)}</b> from the customer directory?<p>Existing order totals will remain saved.</p>`,true))return;await api('/api/customers/'+id,{method:'DELETE'});if(editingCustomerId===id)clearCustomerEdit();await refreshGuests()}
let customerLookupTimer=0,customerLookupTicket=0;
function queueCustomerLookup(){clearTimeout(customerLookupTimer);customerLookupTimer=setTimeout(lookupDeliveryCustomer,300)}
async function lookupDeliveryCustomer(){let phone=$('#cphone')?.value.trim()||'',digits=phone.replace(/\D/g,'');if(digits.length<7){showCustomerMatch('');return}let ticket=++customerLookupTicket,result=await api('/api/customers/lookup?phone='+encodeURIComponent(phone));if(ticket!==customerLookupTicket)return;if(result.found){$('#cname').value=result.name||'';$('#caddress').value=result.address||'';draft.cname=$('#cname').value;draft.cphone=phone;draft.caddress=$('#caddress').value;showCustomerMatch('Customer found · name and address filled automatically','found')}else showCustomerMatch('New customer · complete the name and address fields','new')}
function showCustomerMatch(text,state=''){let el=$('#customer-match');if(!el&&$('#cphone')){$('#cphone').closest('.delivery-input').insertAdjacentHTML('afterend','<div id="customer-match" class="customer-match" aria-live="polite"></div>');el=$('#customer-match')}if(!el)return;el.textContent=text;el.className='customer-match '+state}
function resetDeliveryCustomer(){
 clearTimeout(customerLookupTimer);customerLookupTicket++;
 for(const id of ['cname','cphone','caddress']){draft[id]='';const field=$('#'+id);if(field)field.value=''}
 showCustomerMatch('');
}
let products=[],users=[],selectedProduct=null;
async function loadManagement(){setHead('Owner control center','Manage the menu, user access, and POS settings.');const c=await api('/api/management/categories');$('#management').innerHTML=`<div class="toolbar tabs"><button onclick="adminTab('menu')">Menu & Deals</button><button onclick="adminTab('users')">Users & Roles</button><button onclick="adminTab('system')">System</button></div><div id="admin-menu" class="admin-pane columns"><form class="panel form" onsubmit="event.preventDefault();saveProduct(false)"><label>Category<select id="product-category">${c.filter(c=>c.name!=='Deals').map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label><label>Name<input id="product-name" required></label><label>Description<input id="product-description"></label><label id="product-price-label">Price<input id="product-price" type="number" min="0" step=".01" required></label><div id="product-variants" class="management-variant-fields hidden"></div><button class="primary">ADD MENU ITEM</button></form><div><h2>Current menu</h2><div id="product-list" class="list"></div><div class="toolbar"><button class="gold" onclick="saveProduct(true)">SAVE EDITS</button><button class="deny" onclick="deactivateProduct()">DEACTIVATE</button></div></div></div><div id="admin-users" class="admin-pane columns hidden"><form class="panel form" onsubmit="event.preventDefault();saveUser()"><h2>User credentials</h2><label>Username<input id="new-user" required></label><label>Role<select id="new-role"><option>cashier</option><option>owner</option></select></label><label>Password<input id="new-pass" type="password" required autocomplete="new-password"></label><button class="primary">CREATE / RESET USER</button></form><div><h2>Current users</h2><div id="user-list" class="list"></div></div></div><div id="admin-system" class="admin-pane hidden panel"><h2>System controls</h2><p>Download a complete database snapshot from this server.</p><a class="button" href="/api/management/backup">CREATE DATABASE BACKUP</a><p class="muted">Portable JSON backup includes all tables. Keep it private; restoration requires a database administrator.</p></div>`;await refreshManagement()}
function adminTab(t){document.querySelectorAll('.admin-pane').forEach(x=>x.classList.toggle('hidden',x.id!=='admin-'+t))}
async function refreshManagement(){[products,users]=await Promise.all([api('/api/management/products'),api('/api/management/users')]);$('#product-list').innerHTML=products.map(p=>`<button class="row" onclick="selectProduct(${p.id})"><span><b>${esc(p.name)}</b><br><small>${esc(p.description)}</small></span><b>${money(p.price)}</b></button>`).join('');$('#user-list').innerHTML=users.map(u=>`<div class="row"><button onclick="selectUser(${u.id})">${esc(u.username)} · ${esc(u.role)}</button><span>${u.is_active?'Active':'Inactive'}</span><button onclick="toggleUser(${u.id})">TOGGLE ACTIVE</button></div>`).join('')}
function selectProduct(id){selectedProduct=id;let p=products.find(p=>p.id===id);for(let k of ['name','description','price'])$('#product-'+k).value=p[k];$('#product-category').value=p.category_id}
async function saveProduct(edit){if(edit&&!selectedProduct)return message('Select item','Choose a menu item first.');const variants=[...document.querySelectorAll('#product-variants input[data-variant-name]')].map(input=>({id:Number(input.dataset.variantId)||null,name:input.dataset.variantName,price:Number(input.value)}));let payload={category_id:Number($('#product-category').value),name:$('#product-name').value,description:$('#product-description').value,price:Number($('#product-price').value)||0,variants};await post('/api/management/products'+(edit?'/'+selectedProduct:''),payload,edit?'PUT':'POST');menu=null;await refreshManagement()}
async function deactivateProduct(){if(!selectedProduct)return;if(!await message('Deactivate menu item','Remove this item from the active menu?',true))return;await api('/api/management/products/'+selectedProduct,{method:'DELETE'});selectedProduct=null;menu=null;await refreshManagement()}
function selectUser(id){let u=users.find(u=>u.id===id);$('#new-user').value=u.username;$('#new-role').value=u.role;$('#new-pass').value=''}
async function saveUser(){await post('/api/management/users',{username:$('#new-user').value,password:$('#new-pass').value,role:$('#new-role').value});$('#new-pass').value='';await refreshManagement()}
async function toggleUser(id){await post('/api/management/users/'+id+'/toggle');await refreshManagement()}

const loadManagementWithoutDealCategory=loadManagement;
loadManagement=async function(){await loadManagementWithoutDealCategory();const select=$('#product-category'),form=$('#admin-menu>.form');if(select&&![...select.options].some(option=>option.textContent==='Deals')){const categories=await api('/api/management/categories'),deals=categories.find(category=>category.name==='Deals');if(deals)select.add(new Option('Deals',deals.id))}if(select){select.onchange=()=>renderManagementVariantFields(selectedProduct?products.find(product=>product.id===selectedProduct):null);renderManagementVariantFields()}if(form){form.insertAdjacentHTML('afterbegin','<div class="management-form-heading"><div><h2 id="product-form-title">Add menu item</h2><p id="product-form-help" class="muted">Create a new product or deal.</p></div><button type="button" id="product-form-clear" class="hidden" onclick="clearProductSelection()">CANCEL EDIT</button></div>');const submit=form.querySelector('button.primary');submit.id='product-form-submit';submit.textContent='ADD MENU ITEM';form.onsubmit=event=>{event.preventDefault();saveProduct(Boolean(selectedProduct))}}const list=$('#product-list');if(list&&!$('#management-category-filter')){const categories=[];products.forEach(product=>{if(!categories.includes(product.category))categories.push(product.category)});list.insertAdjacentHTML('beforebegin',`<div class="management-list-controls"><select id="management-category-filter" aria-label="Filter current menu by category" onchange="renderManagementProductList()"><option value="all">All categories</option>${categories.map(category=>`<option value="${esc(category)}">${esc(category)}</option>`).join('')}</select><input id="management-menu-search" type="search" placeholder="Search current menu..." aria-label="Search current menu" oninput="renderManagementProductList()"></div>`);renderManagementProductList()}}

function renderManagementVariantFields(product=null){
 const select=$('#product-category'),host=$('#product-variants'),priceLabel=$('#product-price-label');
 if(!select||!host||!priceLabel)return;
 const category=select.selectedOptions[0]?.textContent||'';
 const defaults=category==='Pizza'?['S 8"','M 11"','L 14"','XL 16"']:category==='Cold Drinks'?['250ml','500ml','1000ml','1500ml','2200ml']:[];
 const variants=defaults.map(name=>product?.variants?.find(item=>item.name===name)||{name,price:''});
 host.classList.toggle('hidden',!defaults.length);
 priceLabel.classList.toggle('hidden',Boolean(defaults.length));
 $('#product-price').required=!defaults.length;
 host.innerHTML=defaults.length?`<h3>Prices by size</h3><div class="management-variant-grid">${variants.map(item=>`<label>${esc(item.name)}<input type="number" min="0" step=".01" required value="${item.price}" data-variant-id="${item.id||''}" data-variant-name="${esc(item.name)}"></label>`).join('')}</div>`:'';
}

function managementProductPrice(product){if(product.category==='Pizza'||product.category==='Cold Drinks')return '';return product.variants?.length>1?product.variants.map(variant=>`${esc(variant.name)} ${money(variant.price)}`).join(' · '):money(product.price)}

function renderManagementProductList(){
 const selectedCategory=$('#management-category-filter')?.value||'all';
 const search=$('#management-menu-search')?.value.trim().toLowerCase()||'';
 const categoryProducts=selectedCategory==='all'?products:products.filter(product=>product.category===selectedCategory);
 const visibleProducts=search?categoryProducts.filter(product=>`${product.name||''} ${product.description||''} ${product.category||''} ${product.price||''}`.toLowerCase().includes(search)):categoryProducts;
 const categoryGroups=[];
 visibleProducts.forEach(product=>{let group=categoryGroups.find(item=>item.name===product.category);if(!group){group={name:product.category,products:[]};categoryGroups.push(group)}group.products.push(product)});
 $('#product-list').innerHTML=categoryGroups.map(group=>`<section class="management-category-group"><div class="management-category-heading"><h3>${esc(group.name)}</h3><span>${group.products.length} ${group.products.length===1?'item':'items'}</span></div><div class="management-category-items">${group.products.map(p=>`<div class="management-product-row${selectedProduct===p.id?' selected':''}" data-product-id="${p.id}"><button class="management-product-main" onclick="selectProduct(${p.id})"><span class="grow"><b>${esc(p.name)}</b><small>${esc(p.description||'No description')}</small></span><small class="management-size-prices">${managementProductPrice(p)}</small></button><button class="gold management-edit" onclick="selectProduct(${p.id})">EDIT</button><button class="deny management-delete" onclick="deleteManagedProduct(${p.id})">DELETE</button></div>`).join('')}</div></section>`).join('')||`<div class="empty">${search?'No menu items match this search.':'No menu items available in this category.'}</div>`;
}

refreshManagement=async function(){
 [products,users]=await Promise.all([api('/api/management/products'),api('/api/management/users')]);
 renderManagementProductList();
 $('#user-list').innerHTML=users.map(u=>`<div class="row"><button onclick="selectUser(${u.id})">${esc(u.username)} · ${esc(u.role)}</button><span>${u.is_active?'Active':'Inactive'}</span><button onclick="toggleUser(${u.id})">TOGGLE ACTIVE</button></div>`).join('')
}

selectProduct=function(id){selectedProduct=id;const p=products.find(product=>product.id===id);if(!p)return;for(const key of ['name','description','price'])$('#product-'+key).value=p[key];$('#product-category').value=p.category_id;renderManagementVariantFields(p);$('#product-form-title').textContent='Edit menu item';$('#product-form-help').textContent=(p.category==='Pizza'||p.category==='Cold Drinks')?'Update every size and its individual price.':'Update the selected item, its category and price.';$('#product-form-submit').textContent='SAVE CHANGES';$('#product-form-clear').classList.remove('hidden');document.querySelectorAll('.management-product-row').forEach(row=>row.classList.toggle('selected',Number(row.dataset.productId)===id));$('#product-name').focus()}

function clearProductSelection(){selectedProduct=null;const form=$('#admin-menu>.form');if(!form)return;form.reset();renderManagementVariantFields();$('#product-form-title').textContent='Add menu item';$('#product-form-help').textContent='Create a new product or deal.';$('#product-form-submit').textContent='ADD MENU ITEM';$('#product-form-clear').classList.add('hidden');document.querySelectorAll('.management-product-row').forEach(row=>row.classList.remove('selected'))}

async function deleteManagedProduct(id){const product=products.find(item=>item.id===id);if(!product)return;if(!await message('Delete menu item',`Remove ${product.name} from the active menu?`,true))return;await api('/api/management/products/'+id,{method:'DELETE'});if(selectedProduct===id)clearProductSelection();menu=null;await refreshManagement()}

const saveManagedProduct=saveProduct;
saveProduct=async function(edit){await saveManagedProduct(edit);clearProductSelection()}

const karachiClockFormatter=new Intl.DateTimeFormat('en-PK',{timeZone:'Asia/Karachi',hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true});
function updateKarachiClock(){const clock=document.querySelector('.pos-clock');if(clock)clock.textContent=karachiClockFormatter.format(new Date()).toUpperCase()}
setInterval(updateKarachiClock,1000);

function receiptItems(items){
 return `<table class="receipt-items"><thead><tr><th>Product</th><th class="receipt-number">Qty</th><th class="receipt-number">Price</th><th class="receipt-number">Amount</th></tr></thead><tbody>${items.map(item=>`<tr><td>${esc(item.name)}</td><td class="receipt-number">${Number(item.quantity)}</td><td class="receipt-number">${money(item.unit_price)}</td><td class="receipt-number">${money(item.total)}</td></tr>`).join('')}</tbody></table>`
}
function receiptFooter(){return '<div class="receipt-footer"><b>Kamran Market, Main Bazar, Pindorian, Islamabad</b><br><span>Phone: 03105407824 &middot; 03700142132</span><br><span>Complaint Number: 03415100734</span></div>'}
function receiptDateTime(value){
 if(!value)return '';
 const source=String(value),date=new Date(/[zZ]|[+-]\d\d:\d\d$/.test(source)?source:source+'Z');
 if(Number.isNaN(date.getTime()))return source;
 return new Intl.DateTimeFormat('en-PK',{timeZone:'Asia/Karachi',year:'numeric',month:'short',day:'2-digit',hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true}).format(date);
}
function receiptOrderNumber(value){
 const text=String(value||''),match=text.match(/^TC-\d{8}-(\d+)$/);
 return match?match[1].padStart(3,'0'):text;
}
function orderDateTimeMarkup(value){
 if(!value)return '<span class="order-date-time"><span>Date unavailable</span></span>';
 const source=String(value),date=new Date(/[zZ]|[+-]\d\d:\d\d$/.test(source)?source:source+'Z');
 if(Number.isNaN(date.getTime()))return `<span class="order-date-time"><span>${esc(source)}</span></span>`;
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Karachi',year:'2-digit',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:true}).formatToParts(date).filter(part=>part.type!=='literal').map(part=>[part.type,part.value]));
 return `<span class="order-date-time"><span>${parts.day}-${parts.month}-${parts.year}</span><span>${parts.hour}:${parts.minute} ${parts.dayPeriod}</span></span>`;
}

function receiptPrintPair(receipt){
 const full=receipt.cloneNode(true),slip=document.createElement('div');
 const orderNumber=receipt.querySelector('.receipt-order b')?.textContent.trim()||'Order';
 const table=receipt.querySelector('.receipt-items')?.outerHTML||'';
 slip.className='kitchen-receipt';
 slip.innerHTML=`<p class="kitchen-order-number">${esc(orderNumber)}</p>${table}`;
 return {full,slip};
}

function requestTopCityPrint(kind,printHtml=''){
 window.__topCityPrintKind=kind;
 // Every native job has an ID. This prevents a delayed completion event from
 // starting or cutting the compact order slip more than once.
 const request={kind,printHtml,claimed:false,id:String(Date.now())+'-'+Math.random()};
 window.__topCityNativePrintRequest=request;
 if(window.topCityPrintBridge&&typeof window.topCityPrintBridge.requestPrint==='function'){
  request.claimed=true;
  window.topCityPrintBridge.requestPrint(kind,printHtml,request.id);
  return request.id;
 }
 // Fallback while the desktop bridge is still loading or in a normal browser.
 window.dispatchEvent(new CustomEvent('topcity-native-print-request',{detail:{kind,printHtml,requestId:request.id}}));
 return request.id;
}

function printReceiptPair(receipt,direct=false){
 document.body.classList.remove('report-print-mode');
 document.querySelector('#report-print-host')?.remove();
 document.querySelector('#thermal-print-host')?.remove();
 const host=document.createElement('div');
 host.id='thermal-print-host';
 const pair=receiptPrintPair(receipt);
 host.appendChild(pair.full);
 document.body.appendChild(host);
 window.__topCityReceiptPrintQueue={host,slip:pair.slip,phase:'full',secondQueued:false,activeRequestId:''};
 prepareThermalReceipt();
 window.__topCityReceiptPrintQueue.activeRequestId=requestTopCityPrint('receipt',host.firstElementChild.outerHTML);
}

window.addEventListener('topcity-receipt-print-complete',event=>{
 const queue=window.__topCityReceiptPrintQueue;
 if(!queue||(event.detail?.requestId&&event.detail.requestId!==queue.activeRequestId))return;
 if(!event.detail?.success){
  queue.host.remove();
  window.__topCityReceiptPrintQueue=null;
  window.__topCityPrintKind='';
  return;
 }
 if(queue.phase==='full'){
  if(queue.secondQueued)return;
  queue.secondQueued=true;
  queue.phase='slip';
  while(queue.host.firstChild)queue.host.removeChild(queue.host.firstChild);
  queue.host.appendChild(queue.slip);
  setTimeout(()=>{
   if(window.__topCityReceiptPrintQueue!==queue)return;
   prepareThermalReceipt();
   queue.activeRequestId=requestTopCityPrint('receipt',queue.host.firstElementChild.outerHTML);
  },250);
  return;
 }
 queue.host.remove();
 window.__topCityReceiptPrintQueue=null;
 window.__topCityPrintKind='';
});

function orderReceiptMarkup(order){
 const customer=order.customer;
 const delivery=order.order_type==='delivery'&&customer?`<p><b>Delivery receiver</b><br><span class="receipt-delivery-name">${esc(customer.name||'')}</span><br>${esc(customer.phone||'')}<br>${esc(customer.address||'')}</p><hr>`:'';
 return `<div id="receipt"><h2>DECENT PIZZA LIVE</h2><p class="receipt-order"><b>Order No-${esc(receiptOrderNumber(order.order_number))}</b><br>${esc(order.order_type)} &middot; ${esc(order.payment_method)}<br>${esc(receiptDateTime(order.created_at))}</p>${delivery}${receiptItems(order.items||[])}<p class="receipt-summary">Subtotal: ${money(order.subtotal)}<br>Discount: ${money(order.discount)}<br>Tax: ${money(order.tax)}<br><b>Total: ${money(order.total)}</b></p><p class="receipt-thanks">Thank you for your order.</p>${receiptFooter()}</div>`;
}

function printOrderReceipt(order){
 const wrapper=document.createElement('div');
 wrapper.innerHTML=orderReceiptMarkup(order);
 printReceiptPair(wrapper.querySelector('#receipt'),true);
}

function printCashbackReceipt(order){
 const wrapper=document.createElement('div');
 wrapper.innerHTML=orderReceiptMarkup(order);
 const receipt=wrapper.querySelector('#receipt'),details=document.createElement('p');
 details.className='receipt-summary';
 details.innerHTML=`Cashback: ${esc(order.cashback_status)}<br>Cashback amount: ${money(order.cashback_amount)}<br>Net after cashback: ${money(order.net_total)}`;
 receipt.querySelector('.receipt-summary')?.insertAdjacentElement('afterend',details);
 printReceiptPair(receipt);
}

async function printSalesReport(){
 const reports=$('#reports');if(!reports)return;
 try{
  const q=query('reports');
  const [rows,dashboard]=await Promise.all([api('/api/orders?'+q),api('/api/dashboard?'+q)]);
  const period=$('#reports-period')?.value||'All dates';
  const status=$('#reports-status')?.selectedOptions?.[0]?.textContent||'All statuses';
  const sort=$('#reports-sort')?.selectedOptions?.[0]?.textContent||'Newest first';
  const search=$('#reports-search')?.value.trim();
  const salesRows=rows.map(order=>`<tr><td><b>Order No-${esc(receiptOrderNumber(order.order_number))}</b><br><small>${esc(receiptDateTime(order.created_at))}</small></td><td>${esc(order.order_type)}<br><small>${esc(order.payment_method)} · ${esc(order.approval_status==='denied'?'rejected':order.approval_status)}</small></td><td>${money(order.net_total)}</td></tr>`).join('')||'<tr><td colspan="3">No sales match these filters.</td></tr>';
  const summary=dashboard.summary||{};
  const host=document.createElement('section');host.id='report-print-host';host.className='thermal-report';
  host.innerHTML=`<h1>DECENT PIZZA LIVE</h1><h2>Sales List Report</h2><p class="report-meta">${esc(period)} · ${esc(status)}<br>Sorted: ${esc(sort)}${search?`<br>Search: ${esc(search)}`:''}</p><p class="report-meta">Printed: ${esc(receiptDateTime(new Date().toISOString()))}</p><hr><p class="report-summary"><b>Orders: ${rows.length}</b><br>Net sales: ${money(summary.net_sales||0)}<br>Cash: ${money(summary.cash||0)} · Online: ${money(summary.online||0)}</p><h3>Sales</h3><table class="report-table"><thead><tr><th>Order</th><th>Details</th><th>Net</th></tr></thead><tbody>${salesRows}</tbody></table><p class="report-end">End of sales list</p>`;
  document.querySelector('#thermal-print-host')?.remove();document.querySelector('#report-print-host')?.remove();document.body.appendChild(host);
  requestTopCityPrint('report',host.outerHTML);
 }catch(error){message('Could not print sales list',esc(error.message||'Please refresh the report and try again.'))}
}

submitOrder=async function(){
 if(busy)return;
 if(!cart.length)return message('Empty order','Add an item first.');
 saveDraft();
 const payload={lines:cart.map(item=>({...item})),order_type:draft.mode,payment_method:draft.payment||'cash',discount:Number(draft.discount||0),tax_rate:Number(draft.tax||0),customer_name:draft.cname,customer_phone:draft.cphone,customer_address:draft.caddress};
 if(draft.mode==='delivery'&&![draft.cname,draft.cphone,draft.caddress].every(value=>value?.trim()))return message('Delivery details','Receiver name, phone and address are required.');
 busy=true;
 try{
  if(!await message('Confirm checkout',`<p>Payment: ${esc(payload.payment_method)}</p><b>${$('#cart-total').innerHTML}</b>`,true))return;
  const order=await post('/api/orders',payload);
  clearCart();
  const delivery=order.order_type==='delivery'?`<p><b>Delivery receiver</b><br><span class="receipt-delivery-name">${esc(payload.customer_name)}</span><br>${esc(payload.customer_phone)}<br>${esc(payload.customer_address)}</p><hr>`:'';
  const body=`<div id="receipt"><h2>DECENT PIZZA LIVE</h2><p class="receipt-order"><b>Order No-${esc(receiptOrderNumber(order.order_number))}</b><br>${esc(order.order_type)} · ${esc(order.payment_method)}<br>${esc(receiptDateTime(order.created_at))}</p>${delivery}${receiptItems(order.items||[])}<p class="receipt-summary">Subtotal: ${money(order.subtotal)}<br>Discount: ${money(order.discount)}<br>Tax: ${money(order.tax)}<br><b>Total: ${money(order.total)}</b></p><p class="receipt-thanks">Thank you for your order.</p>${receiptFooter()}</div>`;
  await message('Sale receipt',body);
 }finally{busy=false}
}

let thermalReceiptPageStyle=null;
function prepareThermalReceipt(){const host=$('#thermal-print-host'),receipt=host?.querySelector('#receipt')||$('#receipt');if(!receipt)return;receipt.style.removeProperty('width');receipt.style.removeProperty('max-width');const measured=host||receipt,heightPx=Math.max(measured.scrollHeight,measured.getBoundingClientRect().height);const heightMm=Math.max(70,Math.ceil(heightPx*25.4/96)+20);if(!thermalReceiptPageStyle){thermalReceiptPageStyle=document.createElement('style');thermalReceiptPageStyle.id='thermal-receipt-page';document.head.appendChild(thermalReceiptPageStyle)}thermalReceiptPageStyle.textContent=`@page{size:80mm ${heightMm}mm portrait;margin:0}`}
window.addEventListener('beforeprint',prepareThermalReceipt);

const showMessageWithoutAutoPrint=message;
message=async function(title,body,confirm=false){if(title!=='Sale receipt')return showMessageWithoutAutoPrint(title,body,confirm);const content=document.createElement('div');content.innerHTML=body;content.querySelector('#receipt+button')?.remove();const pending=showMessageWithoutAutoPrint(title,content.innerHTML,confirm);const ok=$('#confirm-dialog');ok?.addEventListener('click',()=>{const receipt=$('#modal #receipt');if(receipt)printReceiptPair(receipt,true)},{once:true});return pending}

/* Offline-first checkout queue. IndexedDB persists orders until the authenticated
   server accepts them; client_order_id makes every retry idempotent. */
const offlineDbPromise=new Promise((resolve,reject)=>{
 const request=indexedDB.open('top-city-pos-offline',1);
 request.onupgradeneeded=()=>request.result.createObjectStore('orders',{keyPath:'client_order_id'});
 request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
});
async function offlineStore(mode,value){const db=await offlineDbPromise;return new Promise((resolve,reject)=>{const tx=db.transaction('orders',mode),store=tx.objectStore('orders');let request;if(mode==='readonly')request=store.getAll();else if(value?.remove)request=store.delete(value.remove);else request=store.put(value);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)})}
const offlineOrders=()=>offlineStore('readonly');
const removeOfflineOrder=id=>offlineStore('readwrite',{remove:id});
const saveOfflineOrder=record=>offlineStore('readwrite',record);
function newClientOrderId(){return crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=Math.random()*16|0;return(c==='x'?r:r&3|8).toString(16)})}
function offlineReceipt(payload,items){
 const subtotal=items.reduce((sum,item)=>sum+item.total,0),discount=Math.min(subtotal,Math.max(0,payload.discount||0)),tax=Math.round((subtotal-discount)*(payload.tax_rate||0))/100;
 return {id:-Date.now(),order_number:'OFFLINE-'+new Date().toISOString().replace(/\D/g,'').slice(2,14),created_at:new Date().toISOString(),order_type:payload.order_type,payment_method:payload.payment_method,status:'pending',approval_status:'awaiting',subtotal,discount,tax,total:subtotal-discount+tax,net_total:subtotal-discount+tax,items,offline:true};
}
function localBusinessStatus(now=new Date()){
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Karachi',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now).filter(part=>part.type!=='literal').map(part=>[part.type,part.value]));
 const minutes=Number(parts.hour)*60+Number(parts.minute);
 return {open:minutes>=600||minutes<105};
}
async function updateOfflineBadge(){
 const count=(await offlineOrders()).length;let badge=$('#offline-sync-badge');
 if(!badge){badge=document.createElement('div');badge.id='offline-sync-badge';document.body.appendChild(badge)}
 badge.textContent=count?`${count} offline order${count===1?'':'s'} waiting to sync`:(navigator.onLine?'Online · all orders synced':'Offline · orders will be saved locally');
 badge.className=(count||!navigator.onLine)?'offline-sync-badge warning':'offline-sync-badge online';
}
let syncingOfflineOrders=false;
async function flushOfflineOrders(){
 if(syncingOfflineOrders||!navigator.onLine)return;syncingOfflineOrders=true;
 try{
  for(const record of await offlineOrders()){
   let response;
   try{response=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(record.payload)})}catch(_){break}
   if(response.status===401)break;
   if(!response.ok){record.sync_error=(await response.json().catch(()=>({detail:'Sync rejected'}))).detail;await saveOfflineOrder(record);continue}
   await removeOfflineOrder(record.client_order_id);
  }
 }finally{syncingOfflineOrders=false;await updateOfflineBadge();if(activePage==='orders'&&$('#orders-list'))await refreshSales('orders')}
}
submitOrder=async function(){
 if(busy)return;if(!cart.length)return message('Empty order','Add an item first.');saveDraft();
 if(!localBusinessStatus().open)return message('Ordering closed','The daily closing runs at 1:45 AM. New orders can be placed again from 10:00 AM.');
 const items=cart.map(item=>{const info=lineInfo(item);return{name:info.name,quantity:item.quantity,unit_price:Number(info.price),total:Number(info.price)*item.quantity}});
 const payload={lines:cart.map(item=>({...item})),order_type:draft.mode,payment_method:draft.payment||'cash',discount:0,tax_rate:0,customer_name:draft.cname,customer_phone:draft.cphone,customer_address:draft.caddress,client_order_id:newClientOrderId(),client_created_at:new Date().toISOString()};
 if(payload.order_type==='delivery'&&![payload.customer_name,payload.customer_phone,payload.customer_address].every(value=>value?.trim()))return message('Delivery details','Receiver name, phone and address are required.');
 busy=true;
 try{
  if(!await message('Confirm checkout',`<p>Payment: ${esc(payload.payment_method)}</p><b>${$('#cart-total').innerHTML}</b>`,true))return;
  let order;
  try{order=await post('/api/orders',payload);setTimeout(updateOfflineBadge,1000)}catch(error){
   if(!error.network&&(!error.status||error.status<500))throw error;
   order=offlineReceipt(payload,items);await saveOfflineOrder({client_order_id:payload.client_order_id,payload,order,queued_at:order.created_at});await updateOfflineBadge();
  }
  clearCart();
  const delivery=order.order_type==='delivery'?`<p><b>Delivery receiver</b><br>${esc(payload.customer_name)}<br>${esc(payload.customer_phone)}<br>${esc(payload.customer_address)}</p><hr>`:'';
  const notice=order.offline?'<p class="offline-receipt-notice"><b>OFFLINE ORDER</b><br>Saved safely on this device. It will upload automatically when internet returns.</p>':'';
  const body=`<div id="receipt"><h2>DECENT PIZZA LIVE</h2>${notice}<p class="receipt-order"><b>Order No-${esc(receiptOrderNumber(order.order_number))}</b><br>${esc(order.order_type)} · ${esc(order.payment_method)}<br>${esc(receiptDateTime(order.created_at))}</p>${delivery}${receiptItems(order.items||items)}<p class="receipt-summary">Subtotal: ${money(order.subtotal)}<br>Discount: ${money(order.discount)}<br>Tax: ${money(order.tax)}<br><b>Total: ${money(order.total)}</b></p><p class="receipt-thanks">Thank you for your order.</p>${receiptFooter()}</div>`;
  await message('Sale receipt',body);
  if(payload.order_type==='delivery')resetDeliveryCustomer();
 }finally{busy=false}
};
const onlineRefreshSales=refreshSales;
refreshSales=async function(page){
 let onlineWorked=true;try{await onlineRefreshSales(page)}catch(error){if(!error.network&&(!error.status||error.status<500))throw error;onlineWorked=false}
 const pending=await offlineOrders(),list=$('#'+page+'-list');if(!list)return;
 const rows=pending.map(record=>record.order).sort((a,b)=>b.created_at.localeCompare(a.created_at));
 const pendingHtml=rows.map(order=>`<div class="row offline-order-row"><span class="grow"><b>${esc(order.order_number)}</b><br><small>${esc(order.order_type)} · ${esc(order.payment_method)} · saved locally</small></span><b>${money(order.total)}</b><span class="badge pending">WAITING TO SYNC</span></div>`).join('');
 if(pendingHtml)list.insertAdjacentHTML('afterbegin',pendingHtml);else if(!onlineWorked)list.innerHTML='<div class="empty">Offline. No locally saved orders are waiting.</div>';
};
const onlineShowApp=showApp;
showApp=function(account){onlineShowApp(account);flushOfflineOrders()};
window.addEventListener('online',()=>{updateOfflineBadge();flushOfflineOrders()});
window.addEventListener('offline',updateOfflineBadge);
setInterval(flushOfflineOrders,15000);
updateOfflineBadge();

/* Standalone desktop synchronization. Orders accepted by the local SQLite
   server are queued there and uploaded to the Railway API in the background. */
const browserQueueBadge=updateOfflineBadge;
updateOfflineBadge=async function(){
 try{
  const status=await api('/api/sync/status');
  if(!status.enabled)return browserQueueBadge();
  let badge=$('#offline-sync-badge');
  if(!badge){badge=document.createElement('div');badge.id='offline-sync-badge';document.body.appendChild(badge)}
  if(status.pending){badge.textContent=`${status.pending} local order${status.pending===1?'':'s'} waiting for Railway`;badge.className='offline-sync-badge warning'}
  else if(status.remote_url&&status.token_configured){badge.textContent='Online sync ready · all orders synchronized';badge.className='offline-sync-badge online'}
  else{badge.textContent='Offline database · configure Railway sync in System';badge.className='offline-sync-badge warning'}
 }catch(_){await browserQueueBadge()}
};

async function loadSyncPanel(){
 const host=$('#admin-system');if(!host)return;
 const status=await api('/api/management/sync-settings');
 if(!status.enabled)return;
 let panel=$('#sync-settings-panel');
 if(!panel){
  host.insertAdjacentHTML('beforeend',`<section id="sync-settings-panel" class="sync-settings"><h2>Railway synchronization</h2><p class="muted">The offline database remains primary when internet is unavailable. When connected, pending orders are securely copied to the Railway PostgreSQL database.</p><label>Public Railway application URL<input id="sync-remote-url" type="url" placeholder="https://your-pos.up.railway.app"></label><label>Synchronization token<input id="sync-token" type="password" autocomplete="new-password" placeholder="Enter token to set or replace it"></label><div class="toolbar"><button class="primary" onclick="saveRailwaySync()">SAVE CONNECTION</button><button onclick="runRailwaySync()">SYNC NOW</button></div><div id="sync-status" class="sync-status"></div></section>`);
  panel=$('#sync-settings-panel');
 }
 $('#sync-remote-url').value=status.remote_url||'';
 renderSyncStatus(status);
}
function renderSyncStatus(status){
 const box=$('#sync-status');if(!box)return;
 const ready=status.remote_url&&status.token_configured;
 box.className='sync-status '+(status.pending?'warning':ready?'ready':'');
 box.innerHTML=`<b>${ready?'Connection configured':'Connection not configured'}</b><span>Pending: ${status.pending||0} · Failed attempts: ${status.failed||0}</span><span>${status.last_synced_at?'Last synchronized: '+esc(status.last_synced_at):'No completed synchronization yet'}</span>`;
}
async function saveRailwaySync(){
 const remote_url=$('#sync-remote-url').value.trim(),token=$('#sync-token').value.trim();
 try{const status=await post('/api/management/sync-settings',{remote_url,token:token||null},'PUT');$('#sync-token').value='';renderSyncStatus(status);await updateOfflineBadge();await message('Synchronization saved','The offline POS will retry pending orders automatically every 15 seconds.')}catch(error){await message('Cannot save synchronization',esc(error.message))}
}
async function runRailwaySync(){
 try{const status=await post('/api/management/sync-now');renderSyncStatus(status);await updateOfflineBadge();await message(status.ok?'Synchronization complete':'Synchronization pending',esc(status.message||'Synchronization pass finished.'))}catch(error){await message('Synchronization failed',esc(error.message))}
}
const managementWithSync=loadManagement;
loadManagement=async function(){await managementWithSync();await loadSyncPanel();mountHeaderControls('#management>.tabs')};
const appWithSyncStatus=showApp;
showApp=function(account){appWithSyncStatus(account);setTimeout(updateOfflineBadge,500)};
setInterval(updateOfflineBadge,15000);

let coldDrinksRequest=0;
function coldDrinksQuery(){return query('cold-drinks')}
function sortColdDrinkRows(rows,sort,type){
 const sizeRank=value=>({'250ml':250,'500ml':500,'1000ml':1000,'1500ml':1500,'2200ml':2200,'Unspecified':9000,'Unknown size':9999}[value]??9999);
 return [...rows].sort((a,b)=>{
  if(sort==='quantity-high'||sort==='quantity-low')return (Number(a.quantity)-Number(b.quantity))*(sort==='quantity-high'?-1:1);
  if(type==='direct'&&(sort==='sales-high'||sort==='sales-low'))return (Number(a.revenue)-Number(b.revenue))*(sort==='sales-high'?-1:1);
  if(sort==='size')return sizeRank(a.size)-sizeRank(b.size)||(a.brand||a.deal).localeCompare(b.brand||b.deal);
  return (a.brand||a.deal).localeCompare(b.brand||b.deal)||sizeRank(a.size)-sizeRank(b.size);
 });
}
async function refreshColdDrinksReport(){
 const ticket=++coldDrinksRequest,queryParams=coldDrinksQuery(),host=$('#cold-drinks-report');
 if(!host)return;
 try{
  const data=await api('/api/cold-drinks-report?'+queryParams),summary=data.summary;
  if(ticket!==coldDrinksRequest)return;
  const sort=$('#cold-drinks-sort')?.value||'brand';
  const directRows=sortColdDrinkRows(data.direct,sort,'direct').map(row=>`<tr><td>${esc(row.brand)}</td><td>${esc(row.size)}</td><td>${row.quantity}</td><td>${money(row.revenue)}</td></tr>`).join('')||'<tr><td colspan="4">No separately sold cold drinks in this period.</td></tr>';
  const dealRows=sortColdDrinkRows(data.included_in_deals,sort,'deal').map(row=>`<tr><td>${esc(row.deal)}</td><td>${esc(row.size)}</td><td>${row.quantity}</td></tr>`).join('')||'<tr><td colspan="3">No cold drinks included in deals in this period.</td></tr>';
  host.innerHTML=`<div class="cold-drinks-heading"><div><h2>Cold Drinks report</h2><p>Tracked separately by brand and bottle size, including drinks contained in deals.</p></div></div><div class="cards cold-drinks-summary"><div class="card"><small>Direct bottles</small><div class="value">${summary.direct_units}</div></div><div class="card"><small>Bottles in deals</small><div class="value">${summary.deal_units}</div></div><div class="card"><small>Total cold drinks</small><div class="value">${summary.total_units}</div></div><div class="card"><small>Direct drink sales</small><div class="value">${money(summary.direct_revenue)}</div></div></div><div class="cold-drinks-tables"><section><h3>Sold separately</h3><table><thead><tr><th>Brand</th><th>Size</th><th>Qty</th><th>Sales</th></tr></thead><tbody>${directRows}</tbody></table></section><section><h3>Included in deals</h3><table><thead><tr><th>Deal</th><th>Drink size</th><th>Bottles</th></tr></thead><tbody>${dealRows}</tbody></table><p class="muted">Deal drink revenue remains part of the deal package total; it is not counted again as direct drink revenue.</p></section></div>`;
 }catch(error){if(ticket===coldDrinksRequest)host.innerHTML='<h2>Cold Drinks report</h2><div class="empty">Cold-drink totals are temporarily unavailable.</div>'}
}

async function printColdDrinksReport(){
 const report=$('#cold-drinks-report');if(!report)return;
 try{
  const q=coldDrinksQuery(),data=await api('/api/cold-drinks-report?'+q);
  const period=$('#cold-drinks-period')?.value||'All dates';
  const status=$('#cold-drinks-status')?.selectedOptions?.[0]?.textContent||'All statuses';
  const sortValue=$('#cold-drinks-sort')?.value||'brand';
  const sort=$('#cold-drinks-sort')?.selectedOptions?.[0]?.textContent||'Brand A-Z';
  const search=$('#cold-drinks-search')?.value.trim();
  const direct=sortColdDrinkRows(data.direct||[],sortValue,'direct');
  const deals=sortColdDrinkRows(data.included_in_deals||[],sortValue,'deal');
  const directRows=direct.map(row=>`<tr><td>${esc(row.brand)}</td><td>${esc(row.size)}</td><td>${Number(row.quantity)||0}</td><td>${money(row.revenue)}</td></tr>`).join('')||'<tr><td colspan="4">No separately sold cold drinks.</td></tr>';
  const dealRows=deals.map(row=>`<tr><td>${esc(row.deal)}</td><td>${esc(row.size)}</td><td>${Number(row.quantity)||0}</td></tr>`).join('')||'<tr><td colspan="3">No cold drinks in deals.</td></tr>';
  const summary=data.summary||{};
  const host=document.createElement('section');host.id='report-print-host';host.className='thermal-report';
  host.innerHTML=`<h1>DECENT PIZZA LIVE</h1><h2>Cold Drinks Report</h2><p class="report-meta">${esc(period)} · ${esc(status)}<br>Sorted: ${esc(sort)}${search?`<br>Search: ${esc(search)}`:''}</p><p class="report-meta">Printed: ${esc(receiptDateTime(new Date().toISOString()))}</p><hr><p class="report-summary">Direct bottles: ${Number(summary.direct_units)||0}<br>In deals: ${Number(summary.deal_units)||0}<br><b>Total bottles: ${Number(summary.total_units)||0}</b><br>Direct sales: ${money(summary.direct_revenue||0)}</p><h3>Sold Separately</h3><table class="report-table report-table-tight"><thead><tr><th>Brand</th><th>Size</th><th>Qty</th><th>Sales</th></tr></thead><tbody>${directRows}</tbody></table><h3>Included in Deals</h3><table class="report-table"><thead><tr><th>Deal</th><th>Size</th><th>Qty</th></tr></thead><tbody>${dealRows}</tbody></table><p class="report-note">Deal drink revenue is included in the deal total.</p><p class="report-end">End of cold drinks report</p>`;
  document.querySelector('#thermal-print-host')?.remove();document.querySelector('#report-print-host')?.remove();document.body.appendChild(host);
  requestTopCityPrint('report',host.outerHTML);
 }catch(error){message('Could not print cold drinks report',esc(error.message||'Please refresh the report and try again.'))}
}

function mountColdDrinksReport(){
 if($('#cold-drinks-panel'))return;
 const salesList=$('#reports-list');
 salesList.insertAdjacentHTML('beforebegin',`<div id="reports-results-grid" class="reports-results-grid"><section class="report-list-column sales-report-column"><div class="report-column-title"><h2>Sales list</h2><p class="muted">Orders matching the selected sales filters.</p><div class="toolbar sales-list-actions"><button class="primary" onclick="printSalesReport()">PRINT SALES LIST</button></div></div><div id="sales-list-slot"></div></section><section id="cold-drinks-panel" class="cold-drinks-panel report-list-column"><div class="cold-report-title"><h2>Cold Drinks Report</h2><p class="muted">Filter, sort and print cold drinks independently.</p></div>${filters('cold-drinks',true)}<div class="toolbar cold-drinks-actions"><button onclick="refreshColdDrinksReport()">Refresh</button><button class="primary" onclick="printColdDrinksReport()">Print</button></div><section id="cold-drinks-report" class="cold-drinks-report"></section></section></div>`);
 $('#sales-list-slot').appendChild(salesList);
 const sort=$('#cold-drinks-sort');
 sort.innerHTML='<option value="brand">Brand A-Z</option><option value="size">Bottle size</option><option value="quantity-high">Quantity: high to low</option><option value="quantity-low">Quantity: low to high</option><option value="sales-high">Sales: high to low</option><option value="sales-low">Sales: low to high</option>';
 document.querySelectorAll('#cold-drinks-panel select,#cold-drinks-panel input').forEach(control=>control.onchange=refreshColdDrinksReport);
 $('#cold-drinks-search').placeholder='Search brand, size, or deal...';
 $('#cold-drinks-search').oninput=refreshColdDrinksReport;
 refreshColdDrinksReport();
}

const loadSalesWithoutClosingReports=loadSales;
loadSales=async function(page){
 await loadSalesWithoutClosingReports(page);
 if(page!=='reports')return;
 mountColdDrinksReport();
 const salesStats=$('#reports-stats');
 salesStats.insertAdjacentHTML('beforebegin','<section id="reports-sticky-stats" class="reports-sticky-stats"><section id="closing-reports" class="closing-reports"></section></section>');
 $('#reports-sticky-stats').appendChild(salesStats);
 const host=$('#closing-reports');
 try{
  const reports=await api('/api/closing-reports'),latest=reports[0];
  host.innerHTML=latest?`<h2>Daily closing report</h2><div class="cards closing-report-cards"><div class="card"><small>Business date</small><div class="value closing-date">${esc(latest.business_date)}</div><p>10:00 AM – 1:45 AM</p></div><div class="card"><small>Orders</small><div class="value">${latest.orders}</div><p>Automatically closed</p></div><div class="card"><small>Net sales</small><div class="value">${money(latest.net_sales)}</div><p>Gross ${money(latest.gross_sales)}</p></div><div class="card"><small>Payments</small><p>Cash ${money(latest.cash)}<br>Card ${money(latest.card)}<br>Online ${money(latest.online)}</p></div><div class="card"><small>Expenses &amp; final net</small><div class="value">${money(latest.net_after_expenses)}</div><p>Expenses ${money(latest.expenses)}</p></div></div>`:'<h2>Daily closing report</h2><div class="empty">The first report will be generated automatically after 1:45 AM.</div>';
 }catch(error){host.innerHTML='<h2>Daily closing report</h2><div class="empty">Closing reports are temporarily unavailable.</div>'}
};

// Qt WebEngine can paint its native orange focus frame around controls after a
// mouse click. Release click focus without changing the app's own active class,
// so selected tabs keep their dark border, shadow and marker.
document.addEventListener('click',event=>{
 const control=event.target.closest('button,a,[role="button"],[role="tab"]');
 if(control)setTimeout(()=>control.blur(),0);
});

// Keep the payment summary and Checkout visible at all times. The delivery
// fields and order lines share the scroll area above it, so both modes remain
// usable on compact all-in-one POS displays.
function arrangeCurrentOrderScroller(){
 const panel=$('.pos-cart'),cart=panel?.querySelector('.cart');
 const delivery=panel?.querySelector('#delivery-fields'),lines=panel?.querySelector('#cart-lines');
 if(!panel||!cart||!delivery||!lines||cart.querySelector('.pos-cart-scroll'))return;
 const scroll=document.createElement('div');
 scroll.className='pos-cart-scroll';
 cart.insertBefore(scroll,cart.firstChild);
 scroll.appendChild(delivery);
 scroll.appendChild(lines);
}

const openPageWithStickyCheckout=openPage;
openPage=async function(page){
 await openPageWithStickyCheckout(page);
 if(page==='pos')arrangeCurrentOrderScroller();
};
window.addEventListener('topcity-report-print-complete',()=>{
 document.body.classList.remove('report-print-mode');
 document.querySelector('#report-print-host')?.remove();
 window.__topCityPrintKind='';
});