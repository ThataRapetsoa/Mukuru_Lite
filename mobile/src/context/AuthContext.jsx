import { createContext, useContext, useState, useEffect } from "react";
import { api } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem("mukuru_user");
    if (stored) {
      setUser(JSON.parse(stored));
    }
    setLoading(false);
  }, []);

  const login = async (fullName, phoneNumber, email) => {
    try {
      const newUser = await api.createUser({
        full_name: fullName,
        phone_number: phoneNumber,
        email: email || null,
      });
      setUser(newUser);
      localStorage.setItem("mukuru_user", JSON.stringify(newUser));
      return newUser;
    } catch (error) {
      if (error.message.includes("already registered")) {
        throw new Error("This phone number is already registered. Try a different number for the demo.");
      }
      throw error;
    }
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem("mukuru_user");
  };

  const refreshUser = async () => {
    if (user) {
      const fresh = await api.getUser(user.id);
      setUser(fresh);
      localStorage.setItem("mukuru_user", JSON.stringify(fresh));
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
