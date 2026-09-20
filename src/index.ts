import express, { Request, Response } from "express";
import cors from "cors";
import dotenv from "dotenv";
import {
  addMenuItem,
  createOrder,
  findMenuItem,
  findOrder,
  getMenuItems,
  getOrders,
} from "./store";
import { OrderItem } from "./types";

dotenv.config();

const app = express();
const PORT = process.env.PORT ? Number(process.env.PORT) : 3000;

app.use(cors());
app.use(express.json());

// Health check
app.get("/api/health", (_req: Request, res: Response) => {
  res.json({
    status: "ok",
    service: "city-top-pos",
    timestamp: new Date().toISOString(),
  });
});

// Menu items
app.get("/api/items", (_req: Request, res: Response) => {
  res.json({ items: getMenuItems() });
});

app.post("/api/items", (req: Request, res: Response) => {
  const { name, price, category, available } = req.body ?? {};

  if (!name || typeof price !== "number") {
    return res.status(400).json({
      error: "Invalid payload. 'name' (string) and 'price' (number) are required.",
    });
  }

  const item = addMenuItem({
    name,
    price,
    category: category ?? "Uncategorized",
    available: available ?? true,
  });

  res.status(201).json({ item });
});

// Orders
app.get("/api/orders", (_req: Request, res: Response) => {
  res.json({ orders: getOrders() });
});

app.get("/api/orders/:id", (req: Request, res: Response) => {
  const order = findOrder(req.params.id);

  if (!order) {
    return res.status(404).json({ error: `Order '${req.params.id}' not found.` });
  }

  res.json({ order });
});

app.post("/api/orders", (req: Request, res: Response) => {
  const { items, customerName } = req.body ?? {};

  if (!Array.isArray(items) || items.length === 0) {
    return res.status(400).json({
      error: "Invalid payload. 'items' must be a non-empty array of { itemId, quantity }.",
    });
  }

  const orderItems: OrderItem[] = [];
  let total = 0;

  for (const requested of items) {
    const menuItem = findMenuItem(requested.itemId);

    if (!menuItem) {
      return res.status(400).json({ error: `Menu item '${requested.itemId}' not found.` });
    }

    const quantity = Number(requested.quantity) > 0 ? Number(requested.quantity) : 1;
    const lineTotal = menuItem.price * quantity;
    total += lineTotal;

    orderItems.push({
      itemId: menuItem.id,
      name: menuItem.name,
      quantity,
      price: menuItem.price,
    });
  }

  const order = createOrder({
    items: orderItems,
    total: Math.round(total * 100) / 100,
    status: "pending",
    customerName,
  });

  res.status(201).json({ order });
});

// Fallback 404 handler
app.use((_req: Request, res: Response) => {
  res.status(404).json({ error: "Not found" });
});

app.listen(PORT, () => {
  console.log(`City Top POS server listening on port ${PORT}`);
});

export default app;
