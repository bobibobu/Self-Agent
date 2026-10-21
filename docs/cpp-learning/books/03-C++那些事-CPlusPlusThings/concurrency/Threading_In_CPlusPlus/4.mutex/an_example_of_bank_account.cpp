#include <iostream>
#include <thread>
#include <mutex>
#include <vector>

using namespace std;

class BankAccount {
public:
    BankAccount() : balance(0) {}

   
    void deposit(int amount) {
        lock_guard<mutex> lock(mtx);  
        balance += amount;
    }


    void withdraw(int amount) {
        lock_guard<mutex> lock(mtx);  
        if (balance >= amount) {
            balance -= amount;
        } else {
            cout << "Not enough funds to withdraw " << amount << endl;
        }
    }


    int get_balance() const {
        return balance;
    }

private:
    int balance;      
    mutable mutex mtx;  
};

void deposit_to_account(BankAccount& account) {
    for (int i = 0; i < 1000; ++i) {
        account.deposit(1);  
    }
}

void withdraw_from_account(BankAccount& account) {
    for (int i = 0; i < 500; ++i) {
        account.withdraw(1); 
    }
}

int main() {
    BankAccount account;

    thread t1(deposit_to_account, ref(account));
    thread t2(withdraw_from_account, ref(account));
    thread t3(deposit_to_account, ref(account));
    thread t4(withdraw_from_account, ref(account));

    t1.join();
    t2.join();
    t3.join();
    t4.join();

    cout << "Final balance: " << account.get_balance() << endl;

    return 0;
}
