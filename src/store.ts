import { MenuItem, Order } from "./types";

/**
 * Simple in-memory data store for the POS application.
 * Replace with a real database for production use.
 */

let menuItems: MenuItem[] = [
  {
    id: "item-1",
    name: "Cheeseburger",
    price: 8.99,
    category: "Main",
    available: true,
  },
  {
    id: "item-2",
    name: "French Fries",
    price: 3.49,
    category: "Side",
    available: true,
  },
  {
    id: "item-3",
    name: "Soft Drink",
    price: 1.99,
    category: "Beverage",
    available: true,
  },
  {
    id: "item-4",
    name: "Caesar Salad",
    price: 6.5,
    category: "Salad",
    available: true,
  },
];

let orders: Order[] = [];

let itemIdCounter = menuItems.length + 1;
let orderIdCounter = 1;

export function getMenuItems(): MenuItem[] {
  return menuItems;
}

export function addMenuItem(data: Omit<MenuItem, "id">): MenuItem {
  const item: MenuItem = {
    id: `item-${itemIdCounter++}`,
    ...data,
  };
  menuItems.push(item);
  return item;
}

export function findMenuItem(id: string): MenuItem | undefined {
  return menuItems.find((item) => item.id === id);
}

export function getOrders(): Order[] {
  return orders;
}

export function findOrder(id: string): Order | undefined {
  return orders.find((order) => order.id === id);
}

export function createOrder(order: Omit<Order, "id" | "createdAt" | "updatedAt">): Order {
  const now = new Date().toISOString();
  const newOrder: Order = {
    id: `order-${orderIdCounter++}`,
    createdAt: now,
    updatedAt: now,
    ...order,
  };
  orders.push(newOrder);
  return newOrder;
}
