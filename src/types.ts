export interface MenuItem {
  id: string;
  name: string;
  price: number;
  category: string;
  available: boolean;
}

export interface OrderItem {
  itemId: string;
  name: string;
  quantity: number;
  price: number;
}

export type OrderStatus = "pending" | "preparing" | "completed" | "cancelled";

export interface Order {
  id: string;
  items: OrderItem[];
  total: number;
  status: OrderStatus;
  customerName?: string;
  createdAt: string;
  updatedAt: string;
}
